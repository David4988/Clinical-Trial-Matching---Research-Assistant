import type { RiskLevel, TrialOverview } from "../../types/monitoring";
import type { ObligationStatus, QueueItem } from "../../types/obligations";
import { RiskSwatch } from "./RiskMark";

/**
 * The operations board's focal panel: who the cohort is, and what work is
 * outstanding on it. One surface rather than three cards, because three
 * equally-weighted boxes gave the screen no place to look first — and
 * because a lone bar in its own card reads as a broken chart rather than as
 * "one obligation".
 *
 * Every number is a tally of a field the backend already decided —
 * `risk_counts` from `GET /monitoring/trials/{id}/overview`, `status` and
 * `patient_id` from `GET /obligations/queue`. Percentages are computed from
 * those same counts. Nothing here is derived clinically, and there is no
 * history to trend against, so nothing trends.
 */

const OPEN_STATUSES = new Set<ObligationStatus>(["OPEN", "AWAITING_RESPONSE"]);

/** The lifecycle exactly as `schema/obligation_enums.py::ObligationStatus`
 * defines it. Live work first, closed work after. */
const STATUS_ORDER: ObligationStatus[] = ["OPEN", "AWAITING_RESPONSE", "RESOLVED", "DISMISSED"];

const STATUS_LABEL: Record<ObligationStatus, string> = {
  OPEN: "Open",
  AWAITING_RESPONSE: "Awaiting response",
  RESOLVED: "Resolved",
  DISMISSED: "Dismissed",
};

/** One hue at three strengths: live work carries the accent, closed work
 * recedes to grey. Deliberately not safe/caution/alert — on this product a
 * red always means the participant. */
const STATUS_FILL: Record<ObligationStatus, string> = {
  OPEN: "var(--color-blue)",
  AWAITING_RESPONSE: "var(--color-blue-mid)",
  RESOLVED: "var(--color-rule-strong)",
  DISMISSED: "var(--color-rule)",
};

/** Attention-first, matching `PatientStatusMap` and the backend's own
 * `_ATTENTION_ORDER` (`app/monitoring/service.py`). */
const RISK_ORDER: RiskLevel[] = ["RED", "UNKNOWN", "AMBER", "GREEN"];

const RISK_STROKE: Record<RiskLevel, string> = {
  GREEN: "var(--color-safe)",
  AMBER: "var(--color-caution)",
  RED: "var(--color-alert)",
  UNKNOWN: "var(--color-rule-strong)",
};

const MAX_PATIENT_ROWS = 6;

export function TrialOperationsOverview({
  overview,
  queueItems,
  onSelect,
}: {
  overview: TrialOverview;
  queueItems: QueueItem[];
  onSelect: (patientId: string) => void;
}) {
  if (overview.total_patients === 0) return null;

  const openItems = queueItems.filter((item) => OPEN_STATUSES.has(item.status));

  return (
    <section className="panel-focal animate-rise overflow-hidden">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-rule px-6 py-4">
        <h2 className="section-title">Trial operations overview</h2>
        <p className="text-[12px] text-ink-faint">
          {overview.total_patients} patients ·{" "}
          {openItems.length === 0
            ? "no open obligations"
            : `${openItems.length} open obligation${openItems.length === 1 ? "" : "s"}`}
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)]">
        <div className="border-b border-rule px-6 py-6 lg:border-b-0 lg:border-r">
          <PanelLabel>Patient population</PanelLabel>
          <RiskDonut riskCounts={overview.risk_counts} total={overview.total_patients} />
        </div>

        <div className="flex flex-col px-6 py-6">
          <PanelLabel>Open work</PanelLabel>
          <div className="flex flex-1 flex-col justify-center">
            <ObligationComposition queueItems={queueItems} />
          </div>
        </div>
      </div>

      <div className="border-t border-rule bg-paper/60 px-6 py-6">
        <PanelLabel>Outstanding work by patient</PanelLabel>
        <OutstandingWork items={openItems} onSelect={onSelect} />
      </div>
    </section>
  );
}

function PanelLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-4 text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-faint">
      {children}
    </div>
  );
}

/** "How healthy is the overall trial population?" — the cohort as one ring.
 * The legend carries the count and the share, so the ring is the shape of
 * the answer and the numbers are still readable at projector distance. */
function RiskDonut({
  riskCounts,
  total,
}: {
  riskCounts: Record<RiskLevel, number>;
  total: number;
}) {
  const RADIUS = 54;
  const STROKE = 18;
  const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
  const present = RISK_ORDER.filter((level) => (riskCounts[level] ?? 0) > 0);
  // A hairline between segments reads as separate quantities rather than one
  // continuous smear. Pointless — and visually wrong — with a single segment.
  const GAP = present.length > 1 ? 2 : 0;

  let drawn = 0;
  const summary = RISK_ORDER.map((level) => `${level} ${riskCounts[level] ?? 0}`).join(", ");

  return (
    <div className="flex flex-wrap items-center gap-x-8 gap-y-5">
      <svg
        viewBox="0 0 140 140"
        className="h-[168px] w-[168px] shrink-0"
        role="img"
        aria-label={`Patient population by risk level — ${total} patients: ${summary}`}
      >
        <g transform="rotate(-90 70 70)">
          <circle cx="70" cy="70" r={RADIUS} fill="none" stroke="var(--color-band)" strokeWidth={STROKE} />
          {present.map((level) => {
            const value = riskCounts[level] ?? 0;
            const length = (value / total) * CIRCUMFERENCE;
            const visible = Math.max(length - GAP, 1);
            const segment = (
              <circle
                key={level}
                cx="70"
                cy="70"
                r={RADIUS}
                fill="none"
                stroke={RISK_STROKE[level]}
                strokeWidth={STROKE}
                strokeDasharray={`${visible} ${CIRCUMFERENCE - visible}`}
                strokeDashoffset={-drawn}
              />
            );
            drawn += length;
            return segment;
          })}
        </g>
        <text
          x="70"
          y="70"
          textAnchor="middle"
          className="readout fill-ink text-[34px] font-semibold"
        >
          {total}
        </text>
        <text x="70" y="86" textAnchor="middle" className="fill-ink-faint text-[9px] tracking-[0.14em]">
          PATIENTS
        </text>
      </svg>

      <dl className="min-w-[176px] flex-1 space-y-0.5">
        {RISK_ORDER.map((level) => {
          const value = riskCounts[level] ?? 0;
          const share = total > 0 ? Math.round((value / total) * 100) : 0;
          return (
            <div
              key={level}
              className={`grid grid-cols-[auto_1fr_auto_auto] items-center gap-x-2.5 rounded-[3px] px-1.5 py-1 ${
                value === 0 ? "text-ink-faint" : "text-ink"
              }`}
            >
              <RiskSwatch level={level} />
              <dt className="text-[12px] tracking-[0.02em]">{level}</dt>
              <dd className="readout w-6 text-right text-[14px] font-semibold">{value}</dd>
              <dd className="readout w-10 text-right text-[12px] text-ink-faint">{share}%</dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

/** "How much unresolved work exists?" — the obligation lifecycle as one
 * composition bar. Leading with the count and the dominant state means a
 * trial with a single obligation reads as a deliberate statistic instead of
 * one lonely bar in an empty card. */
function ObligationComposition({ queueItems }: { queueItems: QueueItem[] }) {
  if (queueItems.length === 0) {
    return (
      <p className="text-[13px] leading-relaxed text-ink-mid">
        No obligations have been raised on this trial yet.
      </p>
    );
  }

  const counts = new Map<ObligationStatus, number>();
  for (const item of queueItems) {
    counts.set(item.status, (counts.get(item.status) ?? 0) + 1);
  }
  const rows = STATUS_ORDER.filter((status) => (counts.get(status) ?? 0) > 0);
  const total = queueItems.length;
  const live = rows
    .filter((status) => OPEN_STATUSES.has(status))
    .reduce((sum, status) => sum + (counts.get(status) ?? 0), 0);
  const headline = rows.find((status) => OPEN_STATUSES.has(status)) ?? rows[0];

  return (
    <div>
      <div className="flex items-baseline gap-2.5">
        <span className="readout text-[38px] font-semibold leading-none text-ink">{live}</span>
        <span className="pb-0.5 font-sans text-[13px] text-ink-mid">
          {live === 1 ? "obligation needs action" : "obligations need action"}
          {live > 0 && headline ? ` · mostly ${STATUS_LABEL[headline].toLowerCase()}` : ""}
        </span>
      </div>

      <div className="mt-4 flex h-2.5 w-full max-w-[26rem] overflow-hidden rounded-full bg-band" role="presentation">
        {rows.map((status) => (
          <div
            key={status}
            style={{
              width: `${((counts.get(status) ?? 0) / total) * 100}%`,
              background: STATUS_FILL[status],
            }}
          />
        ))}
      </div>

      <dl className="mt-4 max-w-[26rem] space-y-1.5">
        {rows.map((status) => {
          const value = counts.get(status) ?? 0;
          return (
            <div key={status} className="flex items-center gap-2.5">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: STATUS_FILL[status] }}
                aria-hidden
              />
              <dt className="flex-1 font-sans text-[13px] text-ink">{STATUS_LABEL[status]}</dt>
              <dd className="readout text-[13px] font-semibold text-ink">{value}</dd>
              <dd className="readout w-10 text-right text-[12px] text-ink-faint">
                {Math.round((value / total) * 100)}%
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

/** "Where should the coordinator focus attention?" — open and
 * awaiting-response obligations concentrated by patient, worst first, each
 * row opening that patient through the same navigation the rest of the
 * board uses. The secondary line is the queue's own state for that
 * patient's most pressing item: nothing is computed here. */
function OutstandingWork({
  items,
  onSelect,
}: {
  items: QueueItem[];
  onSelect: (patientId: string) => void;
}) {
  if (items.length === 0) {
    return (
      <p className="text-[13px] leading-relaxed text-ink-mid">
        Nothing outstanding. Every obligation on this trial has been closed.
      </p>
    );
  }

  const byPatient = new Map<string, QueueItem[]>();
  for (const item of items) {
    const existing = byPatient.get(item.patient_id);
    if (existing) existing.push(item);
    else byPatient.set(item.patient_id, [item]);
  }

  const ranked = [...byPatient.entries()].sort((a, b) => b[1].length - a[1].length);
  const shown = ranked.slice(0, MAX_PATIENT_ROWS);
  const overflow = ranked.length - shown.length;
  const max = shown[0][1].length;

  return (
    <div className="space-y-1">
      {shown.map(([patientId, patientItems]) => {
        // The queue arrives already ordered by the backend's own priority
        // rules, so the first item for this patient is the pressing one.
        const lead = patientItems[0];
        const count = patientItems.length;
        return (
          <button
            key={patientId}
            type="button"
            onClick={() => onSelect(patientId)}
            className="group grid w-full grid-cols-[minmax(0,9rem)_minmax(0,26rem)_auto] items-center gap-x-4 rounded-[4px] px-2 py-2.5 text-left transition-colors hover:bg-panel focus-visible:bg-panel"
          >
            <div className="min-w-0">
              <div className="readout truncate text-[14px] font-semibold text-ink">{patientId}</div>
              <div className="truncate text-[11px] text-ink-faint">
                {STATUS_LABEL[lead.status].toLowerCase()}
                {lead.age_days > 0 ? ` · ${lead.age_days}d open` : ""}
              </div>
            </div>

            <div className="h-2.5 w-full overflow-hidden rounded-full bg-band">
              <div
                className="h-full rounded-full transition-[width] duration-300"
                style={{ width: `${(count / max) * 100}%`, background: "var(--color-blue)" }}
                aria-hidden
              />
            </div>

            <div className="flex items-baseline gap-1.5">
              <span className="readout text-[16px] font-semibold text-ink">{count}</span>
              <span className="text-[11px] text-ink-faint">open</span>
            </div>
          </button>
        );
      })}
      {overflow > 0 && (
        <p className="px-2 pt-1 text-[11px] text-ink-faint">
          +{overflow} more patient{overflow === 1 ? "" : "s"} with outstanding work
        </p>
      )}
    </div>
  );
}
