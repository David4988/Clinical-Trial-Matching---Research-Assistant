import { useCallback, useEffect, useState } from "react";
import { ScreeningApiError } from "../../api/client";
import {
  approveProposal,
  dismissObligation,
  fetchLedger,
  fetchObligation,
  fetchQueue,
  investigate,
  rejectProposal,
} from "../../api/obligations";
import type { ApiError } from "../../types/canonical";
import type {
  Obligation,
  ObligationAction,
  ProposedAction,
  QueueItem,
  QueueResponse,
} from "../../types/obligations";

/**
 * The Work Queue: "what needs my attention right now?" — the researcher
 * surface the obligation layer exists to fill. Container owns fetching and
 * view state only, same convention as `MonitoringApp`; every priority,
 * status and draft arrives already computed by the backend.
 *
 * Works with no AI: `/investigate` always returns a usable deterministic
 * draft (`docs/FINAL_IMPLEMENTATION_PLAN.md` §20.4), so this view never has
 * a "the model is down" state to render.
 */

const TRIAL_ID = "CT-001";

type View = { kind: "list" } | { kind: "item"; id: string };

const PRIORITY_STYLE: Record<string, string> = {
  URGENT: "bg-signal text-paper",
  HIGH: "bg-ink text-paper",
  MEDIUM: "border border-ink text-ink",
  LOW: "border border-rule text-ink-mid",
};

export function WorkQueueApp() {
  const [view, setView] = useState<View>({ kind: "list" });
  const [queue, setQueue] = useState<QueueResponse | null>(null);
  const [obligation, setObligation] = useState<Obligation | null>(null);
  const [ledger, setLedger] = useState<ObligationAction[]>([]);
  const [proposal, setProposal] = useState<ProposedAction | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const asApiError = (err: unknown): ApiError =>
    err instanceof ScreeningApiError
      ? err.error
      : {
          code: "NETWORK_ERROR",
          message: "Could not reach the obligation service.",
          details: ["Confirm the backend is running on port 8000."],
        };

  const loadQueue = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setQueue(await fetchQueue(TRIAL_ID));
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const loadItem = useCallback(async (id: string) => {
    setBusy(true);
    setError(null);
    setProposal(null);
    try {
      const [ob, actions] = await Promise.all([fetchObligation(id), fetchLedger(id)]);
      setObligation(ob);
      setLedger(actions);
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (view.kind === "list") loadQueue();
    else loadItem(view.id);
  }, [view, loadQueue, loadItem]);

  async function onInvestigate(id: string) {
    setBusy(true);
    setError(null);
    try {
      setProposal(await investigate(id));
      await loadItem(id);
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onApprove(proposalId: string, reviewer: string, note: string) {
    setBusy(true);
    setError(null);
    try {
      setProposal(await approveProposal(proposalId, reviewer, note));
      if (view.kind === "item") await loadItem(view.id);
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onReject(proposalId: string, reviewer: string, note: string) {
    setBusy(true);
    setError(null);
    try {
      setProposal(await rejectProposal(proposalId, reviewer, note));
      if (view.kind === "item") await loadItem(view.id);
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onDismiss(id: string, reviewer: string, note: string) {
    setBusy(true);
    setError(null);
    try {
      await dismissObligation(id, reviewer, note);
      await loadItem(id);
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (view.kind === "item") {
    return (
      <ObligationDetail
        obligation={obligation}
        ledger={ledger}
        proposal={proposal}
        busy={busy}
        error={error}
        onBack={() => setView({ kind: "list" })}
        onInvestigate={() => onInvestigate(view.id)}
        onApprove={onApprove}
        onReject={onReject}
        onDismiss={(reviewer, note) => onDismiss(view.id, reviewer, note)}
      />
    );
  }

  return (
    <QueueList
      queue={queue}
      busy={busy}
      error={error}
      onOpen={(id) => setView({ kind: "item", id })}
      onRefresh={loadQueue}
    />
  );
}

function QueueList({
  queue,
  busy,
  error,
  onOpen,
  onRefresh,
}: {
  queue: QueueResponse | null;
  busy: boolean;
  error: ApiError | null;
  onOpen: (id: string) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-sans text-[15px] font-semibold text-ink">Work Queue</h1>
          <p className="text-[12px] text-ink-mid">
            Trial {TRIAL_ID}
            {queue && (
              <>
                {" "}
                · {queue.counts.total} open · {queue.counts.needs_decision} awaiting your decision ·{" "}
                {queue.counts.awaiting_response} awaiting a response
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="border border-rule-strong px-3 py-1.5 text-[12px] text-ink hover:border-ink"
        >
          Refresh
        </button>
      </div>

      {error && <ErrorBanner error={error} />}

      {busy && !queue && <p className="text-[12px] text-ink-mid">Loading…</p>}

      {queue && queue.items.length === 0 && (
        <div className="border border-rule bg-panel p-8 text-center">
          <p className="font-sans text-[14px] text-ink">Nothing needs you right now.</p>
          <p className="mt-1 text-[12px] text-ink-mid">
            Every detected requirement in {TRIAL_ID} is resolved, dismissed, or has no pending decision.
          </p>
        </div>
      )}

      {queue && queue.items.length > 0 && (
        <div className="divide-y divide-rule border border-rule-strong bg-panel">
          {queue.items.map((item) => (
            <QueueRow key={item.obligation_id} item={item} onOpen={() => onOpen(item.obligation_id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function QueueRow({ item, onOpen }: { item: QueueItem; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-ink/[0.03]"
    >
      <span
        className={`shrink-0 px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.08em] ${PRIORITY_STYLE[item.priority] ?? ""}`}
      >
        {item.priority}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-sans text-[13px] text-ink">{item.title}</span>
        <span className="block truncate text-[11px] text-ink-mid">
          {item.patient_id} · {item.type} · {item.status}
          {item.responsible_party ? ` · ${item.responsible_party.display_name}` : " · unrouted"}
        </span>
      </span>
      {item.needs_human_decision && (
        <span className="shrink-0 bg-signal px-1.5 py-0.5 text-[10px] font-semibold text-paper">
          DECISION NEEDED
        </span>
      )}
      <span className="shrink-0 text-[11px] text-ink-faint">{item.age_days}d</span>
    </button>
  );
}

function ObligationDetail({
  obligation,
  ledger,
  proposal,
  busy,
  error,
  onBack,
  onInvestigate,
  onApprove,
  onReject,
  onDismiss,
}: {
  obligation: Obligation | null;
  ledger: ObligationAction[];
  proposal: ProposedAction | null;
  busy: boolean;
  error: ApiError | null;
  onBack: () => void;
  onInvestigate: () => void;
  onApprove: (proposalId: string, reviewer: string, note: string) => void;
  onReject: (proposalId: string, reviewer: string, note: string) => void;
  onDismiss: (reviewer: string, note: string) => void;
}) {
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");

  if (!obligation) {
    return (
      <div className="space-y-3">
        <BackLink onClick={onBack} />
        {error ? <ErrorBanner error={error} /> : <p className="text-[12px] text-ink-mid">Loading…</p>}
      </div>
    );
  }

  const terminal = obligation.status === "RESOLVED" || obligation.status === "DISMISSED";
  const pendingProposal = proposal && proposal.status === "DRAFT" ? proposal : null;

  return (
    <div className="space-y-4">
      <BackLink onClick={onBack} />
      {error && <ErrorBanner error={error} />}

      <section className="border border-rule-strong bg-panel p-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-sans text-[14px] font-semibold text-ink">{obligation.title}</h2>
          <span className="shrink-0 text-[11px] font-semibold tracking-[0.08em] text-ink-mid">
            {obligation.status}
          </span>
        </div>
        <p className="mt-2 font-sans text-[13px] leading-relaxed text-ink">{obligation.detail}</p>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-ink-mid sm:grid-cols-4">
          <Field label="Patient" value={obligation.patient_id} />
          <Field label="Requirement" value={`${obligation.requirement_ref} (${obligation.protocol_id})`} />
          <Field label="Priority" value={obligation.priority} />
          <Field label="Escalations" value={String(obligation.escalation_count)} />
        </dl>

        {obligation.evidence.length > 0 && (
          <div className="mt-3 border-t border-rule pt-3">
            <div className="text-[10px] font-semibold tracking-[0.1em] text-ink-faint">EVIDENCE</div>
            <ul className="mt-1 space-y-1">
              {obligation.evidence.map((e, i) => (
                <li key={i} className="text-[12px] text-ink-mid">
                  {e.locator && <span className="font-semibold text-ink">{e.locator}: </span>}
                  {e.snippet}
                  {e.note && <span className="text-ink-faint"> — {e.note}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {obligation.resolution && (
          <div className="mt-3 border-t border-rule pt-3 text-[12px] text-ink-mid">
            Resolved by {obligation.resolution.by}: {obligation.resolution.note}
          </div>
        )}
      </section>

      <section className="border border-rule-strong bg-panel p-4">
        <div className="text-[10px] font-semibold tracking-[0.1em] text-ink-faint">FOLLOW-UP LEDGER</div>
        <ol className="mt-2 space-y-1">
          {ledger.map((a) => (
            <li key={a.action_id} className="text-[12px] text-ink-mid">
              <span className="font-semibold text-ink">#{a.seq} {a.kind}</span>
              {" — "}
              {new Date(a.occurred_at).toLocaleString()}
              {a.actor_name ? ` · ${a.actor_name}` : ` · ${a.actor_kind}`}
              {a.note ? ` · ${a.note}` : ""}
            </li>
          ))}
          {ledger.length === 0 && <li className="text-[12px] text-ink-faint">No history yet.</li>}
        </ol>
      </section>

      {!terminal && (
        <section className="border border-rule-strong bg-panel p-4">
          <div className="text-[10px] font-semibold tracking-[0.1em] text-ink-faint">PROPOSED ACTION</div>
          {!pendingProposal ? (
            <div className="mt-2">
              <button
                type="button"
                disabled={busy}
                onClick={onInvestigate}
                className="border border-ink bg-ink px-3 py-1.5 text-[12px] text-paper disabled:opacity-50"
              >
                Draft a request
              </button>
            </div>
          ) : (
            <div className="mt-2 space-y-2">
              <ProvenanceBadge proposal={pendingProposal} />
              <div className="border border-rule p-3">
                <div className="text-[11px] text-ink-mid">
                  To: {pendingProposal.recipient_party_id} · Channel: {pendingProposal.channel}
                </div>
                <div className="mt-1 font-sans text-[13px] font-semibold text-ink">{pendingProposal.subject}</div>
                <p className="mt-1 whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-ink">
                  {pendingProposal.body}
                </p>
              </div>

              <div className="flex flex-wrap items-end gap-2">
                <label className="flex flex-col text-[11px] text-ink-mid">
                  Reviewer
                  <input
                    value={reviewer}
                    onChange={(e) => setReviewer(e.target.value)}
                    className="border border-rule-strong px-2 py-1 text-[12px]"
                  />
                </label>
                <label className="flex flex-1 flex-col text-[11px] text-ink-mid">
                  Note (required)
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    className="border border-rule-strong px-2 py-1 text-[12px]"
                  />
                </label>
                <button
                  type="button"
                  disabled={busy || !reviewer.trim() || !note.trim()}
                  onClick={() => onApprove(pendingProposal.proposal_id, reviewer, note)}
                  className="border border-ink bg-ink px-3 py-1.5 text-[12px] text-paper disabled:opacity-50"
                >
                  Approve &amp; send
                </button>
                <button
                  type="button"
                  disabled={busy || !reviewer.trim() || !note.trim()}
                  onClick={() => onReject(pendingProposal.proposal_id, reviewer, note)}
                  className="border border-rule-strong px-3 py-1.5 text-[12px] text-ink disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            </div>
          )}

          {proposal && proposal.status !== "DRAFT" && (
            <div className="mt-3 border-t border-rule pt-3 text-[12px] text-ink-mid">
              Proposal {proposal.proposal_id}: <span className="font-semibold text-ink">{proposal.status}</span>
              {proposal.execution && (
                <>
                  {" "}via {proposal.execution.provider} ({proposal.execution.channel}) —{" "}
                  {proposal.execution.delivery_status}
                  {proposal.execution.error ? `: ${proposal.execution.error}` : ""}
                </>
              )}
            </div>
          )}

          <div className="mt-3 border-t border-rule pt-3">
            <button
              type="button"
              disabled={busy || !reviewer.trim() || !note.trim()}
              onClick={() => onDismiss(reviewer, note)}
              className="text-[12px] text-ink-mid underline decoration-rule-strong hover:text-ink disabled:opacity-50"
            >
              Dismiss this obligation instead
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

function ProvenanceBadge({ proposal }: { proposal: ProposedAction }) {
  const p = proposal.provenance;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-faint">
      <span className="border border-rule px-1.5 py-0.5">{p.provider_kind}</span>
      {p.model_name && <span>{p.model_name}</span>}
      {p.degraded && <span className="text-signal">DEGRADED</span>}
      {p.unresolved.length > 0 && <span>Could not determine: {p.unresolved.join("; ")}</span>}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] tracking-[0.08em] text-ink-faint">{label}</dt>
      <dd className="text-ink">{value}</dd>
    </div>
  );
}

function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="text-[12px] text-ink-mid hover:text-ink">
      ← Back to queue
    </button>
  );
}

function ErrorBanner({ error }: { error: ApiError }) {
  return (
    <section className="border border-rule-strong bg-panel">
      <div className="hatch h-1.5" />
      <div className="p-3">
        <div className="text-[10px] font-semibold tracking-[0.12em] text-ink">{error.code}</div>
        <p className="mt-1 font-sans text-[13px] leading-relaxed text-ink">{error.message}</p>
      </div>
    </section>
  );
}
