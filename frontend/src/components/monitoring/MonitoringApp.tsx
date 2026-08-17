import { useCallback, useEffect, useState } from "react";
import { ScreeningApiError } from "../../api/client";
import {
  advanceMonitoring,
  fetchInvestigatorReviews,
  fetchLatestCycle,
  fetchModel,
  fetchOverview,
  fetchTimeline,
  recordInvestigatorReview,
  seedDemo,
} from "../../api/monitoring";
import type { ApiError } from "../../types/canonical";
import type {
  InvestigatorAction,
  InvestigatorReview,
  ModelProvenance,
  MonitoringCycleResult,
  MonitoringEvent,
  TrialOverview,
} from "../../types/monitoring";
import { InvestigatorPanel } from "./InvestigatorPanel";
import { ModelBadge } from "./ModelBadge";
import { PatientMonitor } from "./PatientMonitor";
import { PatientTimeline } from "./PatientTimeline";
import { TrialOverviewView } from "./TrialOverview";

/**
 * Container for the Phase 2 views. Owns fetching and view state only — no
 * clinical logic lives here, and nothing is computed client-side: every level,
 * action and decision arrives already derived from the backend.
 *
 * `focus` is the Phase 1 handoff. When screening enrols a participant, the shell
 * passes them here and this container opens straight onto that patient, so the
 * judge follows one person across the phase boundary instead of picking them
 * out of an unrelated seeded cohort.
 */

const TRIAL_ID = "CT-001";

/** How many synthetic windows the per-participant demo walks through. */
const DEMO_WINDOWS = 5;

export interface MonitoringFocus {
  patientId: string;
  trialId: string;
}

type View = { kind: "overview" } | { kind: "patient"; patientId: string };

export function MonitoringApp({ focus }: { focus?: MonitoringFocus | null }) {
  const [view, setView] = useState<View>(
    focus ? { kind: "patient", patientId: focus.patientId } : { kind: "overview" },
  );
  const [overview, setOverview] = useState<TrialOverview | null>(null);
  const [cycle, setCycle] = useState<MonitoringCycleResult | null>(null);
  const [timeline, setTimeline] = useState<MonitoringEvent[]>([]);
  const [reviews, setReviews] = useState<InvestigatorReview[]>([]);
  const [model, setModel] = useState<ModelProvenance | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  //: How far the focused participant has been advanced through the demo windows.
  const [windowIndex, setWindowIndex] = useState(0);

  const asApiError = (err: unknown): ApiError =>
    err instanceof ScreeningApiError
      ? err.error
      : {
          code: "NETWORK_ERROR",
          message: "Could not reach the monitoring service.",
          details: ["Confirm the backend is running on port 8000."],
        };

  const loadOverview = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setOverview(await fetchOverview(TRIAL_ID));
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }, []);

  const loadPatient = useCallback(async (patientId: string) => {
    setBusy(true);
    setError(null);
    try {
      const [nextCycle, events, recorded] = await Promise.all([
        fetchLatestCycle(patientId).catch((err) => {
          // A freshly enrolled participant has no cycle yet. That is a normal
          // state on the handoff path, not an error worth blocking the screen.
          if (err instanceof ScreeningApiError && err.error.code === "NO_CYCLE") {
            return null;
          }
          throw err;
        }),
        fetchTimeline(patientId),
        fetchInvestigatorReviews(patientId),
      ]);
      setCycle(nextCycle);
      setTimeline(events);
      setReviews(recorded);
      setView({ kind: "patient", patientId });
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void fetchModel()
      .then(setModel)
      .catch(() => setModel(null));
  }, []);

  useEffect(() => {
    if (focus) {
      setWindowIndex(0);
      void loadPatient(focus.patientId);
    } else {
      void loadOverview();
    }
  }, [focus, loadOverview, loadPatient]);

  async function onSeed() {
    setBusy(true);
    setError(null);
    try {
      await seedDemo(TRIAL_ID);
      setOverview(await fetchOverview(TRIAL_ID));
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onAdvance() {
    if (view.kind !== "patient") return;
    const trialId = cycle?.trial_id ?? focus?.trialId;
    if (!trialId) return;

    setBusy(true);
    setError(null);
    try {
      const next = await advanceMonitoring(
        view.patientId,
        trialId,
        windowIndex,
        DEMO_WINDOWS,
      );
      setCycle(next);
      setTimeline(await fetchTimeline(view.patientId));
      setWindowIndex((current) => Math.min(current + 1, DEMO_WINDOWS));
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function onReview(
    action: InvestigatorAction,
    reviewer: string,
    note: string,
  ) {
    if (view.kind !== "patient" || !cycle) return;

    setBusy(true);
    setError(null);
    try {
      await recordInvestigatorReview(
        view.patientId,
        action,
        reviewer,
        note,
        cycle.cycle_id,
      );
      const [events, recorded] = await Promise.all([
        fetchTimeline(view.patientId),
        fetchInvestigatorReviews(view.patientId),
      ]);
      setTimeline(events);
      setReviews(recorded);
    } catch (err) {
      setError(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Toolbar
        view={view}
        busy={busy}
        empty={(overview?.total_patients ?? 0) === 0}
        canAdvance={view.kind === "patient" && windowIndex < DEMO_WINDOWS}
        windowIndex={windowIndex}
        onBack={() => {
          setView({ kind: "overview" });
          void loadOverview();
        }}
        onRefresh={() =>
          view.kind === "overview"
            ? void loadOverview()
            : void loadPatient(view.patientId)
        }
        onSeed={onSeed}
        onAdvance={onAdvance}
      />

      {model && <ModelBadge model={model} />}

      {error && <ErrorNotice error={error} />}

      {busy && !overview && !cycle && <Loading />}

      {view.kind === "overview" ? (
        overview && <TrialOverviewView overview={overview} onSelect={loadPatient} />
      ) : cycle ? (
        <div className="space-y-8">
          <PatientMonitor cycle={cycle} />
          <InvestigatorPanel
            cycle={cycle}
            reviews={reviews}
            busy={busy}
            error={null}
            onSubmit={onReview}
          />
          <PatientTimeline events={timeline} />
        </div>
      ) : (
        <AwaitingFirstCycle patientId={view.patientId} busy={busy} />
      )}
    </div>
  );
}

function Toolbar({
  view,
  busy,
  empty,
  canAdvance,
  windowIndex,
  onBack,
  onRefresh,
  onSeed,
  onAdvance,
}: {
  view: View;
  busy: boolean;
  empty: boolean;
  canAdvance: boolean;
  windowIndex: number;
  onBack: () => void;
  onRefresh: () => void;
  onSeed: () => void;
  onAdvance: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-3">
      <div className="flex items-center gap-3">
        {view.kind === "patient" && (
          <button
            type="button"
            onClick={onBack}
            className="border border-rule-strong px-3 py-1.5 text-[12px] hover:border-ink"
          >
            ← All patients
          </button>
        )}
        <span className="eyebrow">
          {view.kind === "overview" ? "Trial overview" : view.patientId}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {busy && <span className="text-[11px] text-ink-faint">working…</span>}

        {view.kind === "patient" && (
          <button
            type="button"
            onClick={onAdvance}
            disabled={busy || !canAdvance}
            title="Ingest the next synthetic observation window and run a monitoring cycle"
            className="border border-ink bg-ink px-3 py-1.5 text-[12px] font-medium text-paper hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-30"
          >
            {canAdvance ? `Advance monitoring (${windowIndex + 1}/${DEMO_WINDOWS})` : "Trajectory complete"}
          </button>
        )}

        <button
          type="button"
          onClick={onRefresh}
          disabled={busy}
          className="border border-rule-strong px-3 py-1.5 text-[12px] hover:border-ink disabled:opacity-40"
        >
          Refresh
        </button>

        {empty && view.kind === "overview" && (
          <button
            type="button"
            onClick={onSeed}
            disabled={busy}
            className="border border-ink bg-ink px-3 py-1.5 text-[12px] font-medium text-paper hover:bg-ink/90 disabled:opacity-40"
          >
            Load demo cohort
          </button>
        )}
      </div>
    </div>
  );
}

function AwaitingFirstCycle({
  patientId,
  busy,
}: {
  patientId: string;
  busy: boolean;
}) {
  return (
    <div className="border border-dashed border-rule-strong bg-panel p-8 text-center">
      <div className="eyebrow">Enrolled · awaiting first observations</div>
      <p className="mx-auto mt-2 max-w-md font-sans text-[13px] leading-relaxed text-ink-mid">
        {patientId} is registered on this trial and has been dosed. Advance
        monitoring to ingest the first observation window and run a cycle.
      </p>
      {busy && (
        <div className="relative mx-auto mt-4 h-0.5 w-40 overflow-hidden bg-band">
          <div className="animate-sweep absolute inset-y-0 w-1/4 bg-ink" />
        </div>
      )}
    </div>
  );
}

function Loading() {
  return (
    <div className="border border-dashed border-rule-strong bg-panel p-8 text-center">
      <div className="relative mx-auto mb-3 h-0.5 w-40 overflow-hidden bg-band">
        <div className="animate-sweep absolute inset-y-0 w-1/4 bg-ink" />
      </div>
      <div className="eyebrow">Loading monitoring data</div>
    </div>
  );
}

function ErrorNotice({ error }: { error: ApiError }) {
  return (
    <div className="border border-alert/35 bg-alert-wash p-4">
      <div className="text-[10px] font-semibold tracking-[0.12em] text-alert">
        {error.code}
      </div>
      <p className="mt-1 font-sans text-[14px] text-ink">{error.message}</p>
      {error.details.length > 0 && (
        <ul className="mt-2 space-y-1 font-sans text-[12px] text-ink-mid">
          {error.details.map((detail, index) => (
            <li key={index}>{detail}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
