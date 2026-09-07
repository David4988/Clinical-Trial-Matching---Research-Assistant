import type { NextDoseDecision, OverviewPatient, RiskLevel } from "../../types/monitoring";
import type { QueueItem } from "../../types/obligations";
import { RiskSwatch, riskTileTone } from "./RiskMark";

/**
 * The population command center: every enrolled patient as one tile, so a
 * researcher reads the whole trial's state in the time it takes to glance at
 * the screen, then drills into any one of them.
 *
 * Every field on a tile is already computed upstream — `OverviewPatient`
 * from `MonitoringService.trial_overview()`, the obligation reason from the
 * same `QueueItem[]` the Work Queue renders. Nothing clinical is decided or
 * recomputed here; this component only groups and orders what already
 * arrived.
 */

/** Attention-first: mirrors the backend's own `_ATTENTION_ORDER`
 * (`app/monitoring/service.py`) — RED, then UNKNOWN, then AMBER — with
 * GREEN appended last since it needs no attention at all. A *display*
 * order, not a clinical judgement; the judgement already happened server
 * side to produce `risk_level` in the first place. */
const DISPLAY_ORDER: RiskLevel[] = ["RED", "UNKNOWN", "AMBER", "GREEN"];

const OPEN_STATUSES = new Set(["OPEN", "AWAITING_RESPONSE"]);

/** The protocol's own next-dose decision, set in sentence case so the tile
 * reads as an instruction rather than as another shouted token. The values
 * are `NextDoseDecision` unchanged — nothing is reworded into a new state. */
const ACTION_LABEL: Record<NextDoseDecision, string> = {
  PROCEED: "Proceed",
  REVIEW_REQUIRED: "Review required",
  HOLD: "Hold",
};

const ACTION_TONE: Record<NextDoseDecision, string> = {
  PROCEED: "text-safe",
  REVIEW_REQUIRED: "text-caution",
  HOLD: "text-alert",
};

function groupOpenObligationsByPatient(queueItems: QueueItem[]): Map<string, QueueItem[]> {
  const byPatient = new Map<string, QueueItem[]>();
  for (const item of queueItems) {
    if (!OPEN_STATUSES.has(item.status)) continue;
    const existing = byPatient.get(item.patient_id);
    if (existing) existing.push(item);
    else byPatient.set(item.patient_id, [item]);
  }
  return byPatient;
}

export function PatientStatusMap({
  patients,
  queueItems,
  onSelect,
}: {
  patients: OverviewPatient[];
  queueItems: QueueItem[];
  onSelect: (patientId: string) => void;
}) {
  if (patients.length === 0) return null;

  const obligationsByPatient = groupOpenObligationsByPatient(queueItems);
  const rank = new Map(DISPLAY_ORDER.map((level, i) => [level, i]));
  const ordered = [...patients].sort(
    (a, b) => (rank.get(a.risk_level) ?? 9) - (rank.get(b.risk_level) ?? 9),
  );

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="section-title">Patient status map</h2>
        <span className="text-[12px] text-ink-faint">most urgent first</span>
      </div>
      <div className="stagger grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
        {ordered.map((patient) => (
          <PatientTile
            key={patient.treatment_id}
            patient={patient}
            obligations={obligationsByPatient.get(patient.patient_id) ?? []}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

function PatientTile({
  patient,
  obligations,
  onSelect,
}: {
  patient: OverviewPatient;
  obligations: QueueItem[];
  onSelect: (patientId: string) => void;
}) {
  const topObligation = obligations[0];
  const extraObligations = obligations.length - 1;

  const parts = [
    patient.patient_id,
    `risk ${patient.risk_level}`,
    patient.next_dose ? patient.next_dose.replace("_", " ") : "not yet assessed",
  ];
  if (topObligation) parts.push(topObligation.title);
  if (obligations.length > 1) parts.push(`${obligations.length} open obligations`);

  const action = patient.next_dose ? ACTION_LABEL[patient.next_dose] : "Not assessed";

  return (
    <button
      type="button"
      onClick={() => onSelect(patient.patient_id)}
      aria-label={parts.join(". ")}
      className={`group flex flex-col rounded-[6px] border p-3.5 text-left shadow-[var(--shadow-raised)] transition-[box-shadow,transform,border-color] duration-150 hover:-translate-y-px hover:border-rule-strong hover:shadow-[var(--shadow-focal)] focus-visible:-translate-y-px focus-visible:shadow-[var(--shadow-focal)] ${riskTileTone(
        patient.risk_level,
      )}`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="readout truncate text-[15px] font-semibold text-ink">
          {patient.patient_id}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          <RiskSwatch level={patient.risk_level} size={9} />
          <span className="text-[10px] font-semibold tracking-[0.1em] text-ink-mid">
            {patient.risk_level}
          </span>
        </span>
      </div>

      <div
        className={`mt-3 font-sans text-[15px] font-semibold leading-none ${
          patient.next_dose ? ACTION_TONE[patient.next_dose] : "text-ink-faint"
        }`}
      >
        {action}
      </div>

      <div className="mt-2 text-[11px] leading-snug text-ink-mid empty:hidden">
        {topObligation ? (
          <>
            {topObligation.title}
            {extraObligations > 0 && (
              <span className="text-ink-faint"> +{extraObligations} more</span>
            )}
          </>
        ) : patient.gated ? (
          <span className="text-ink-faint">Data-quality gate overrode the model</span>
        ) : null}
      </div>

      <div className="mt-3 border-t border-rule/60 pt-2 text-[10px] leading-snug text-ink-faint [margin-top:auto]">
        {patient.drug_name} · dose {patient.dose_count}
      </div>
    </button>
  );
}
