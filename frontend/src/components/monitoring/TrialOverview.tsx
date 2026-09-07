import type { OverviewPatient, TrialOverview } from "../../types/monitoring";
import type { QueueItem } from "../../types/obligations";
import { DoseToken, RiskRail, RiskToken } from "./RiskMark";
import { PatientStatusMap } from "./PatientStatusMap";
import { TrialOperationsOverview } from "./TrialOperationsOverview";

/**
 * The board: how many patients, at what risk, and who needs looking at first.
 *
 * "Requiring attention" leads because it is the only part that prompts action.
 * The full roster sits underneath for context.
 */

export function TrialOverviewView({
  overview,
  queueItems,
  onSelect,
}: {
  overview: TrialOverview;
  /** Open obligations for this trial, already computed by the Work Queue
   * read model (`GET /obligations/queue`). Optional and defaults to empty:
   * the board still works, just without the "why" line on each tile, if the
   * obligation layer is not wired up for this app instance. */
  queueItems?: QueueItem[];
  onSelect: (patientId: string) => void;
}) {
  const needAttention = overview.requiring_attention.length;

  return (
    <section className="space-y-9">
      <div className="panel-raised animate-rise overflow-hidden">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-6 pt-5">
          <div>
            <div className="text-[11px] tracking-[0.04em] text-ink-faint">Trial</div>
            <div className="readout text-[38px] font-semibold leading-none text-ink">
              {overview.trial_id}
            </div>
          </div>
          <p className="max-w-[22rem] pb-1.5 font-sans text-[12px] leading-relaxed text-ink-faint">
            <span className="readout text-ink-mid">{overview.protocol_id}</span> · thresholds are
            synthetic and demonstrate the pipeline, not clinical guidance.
          </p>
        </div>

        <div className="mt-5 grid grid-cols-2 border-t border-rule sm:grid-cols-4">
          <Metric
            label="Patients"
            value={overview.total_patients}
            caption={`enrolled on ${overview.trial_id}`}
          />
          <Metric
            label="Active treatments"
            value={overview.active_treatments}
            caption="course currently running"
          />
          <Metric
            label="Need attention"
            value={needAttention}
            caption="red, amber or unassessable"
            alert={needAttention > 0}
          />
          <Metric
            label="Unassessable"
            value={overview.risk_counts.UNKNOWN ?? 0}
            caption="data not trustworthy"
          />
        </div>
      </div>

      <TrialOperationsOverview overview={overview} queueItems={queueItems ?? []} onSelect={onSelect} />

      <PatientStatusMap
        patients={overview.patients}
        queueItems={queueItems ?? []}
        onSelect={onSelect}
      />

      {needAttention > 0 && (
        <div>
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="section-title">Requiring attention</h2>
            <span className="text-[12px] text-ink-faint">{needAttention} of {overview.patients.length}</span>
          </div>
          <div className="panel-raised overflow-hidden">
            {overview.requiring_attention.map((patient, index) => (
              <PatientRow
                key={patient.treatment_id}
                patient={patient}
                onSelect={onSelect}
                isLast={index === overview.requiring_attention.length - 1}
              />
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="section-title text-ink-mid">All patients</h2>
          <span className="text-[12px] text-ink-faint">
            {overview.patients.length} enrolled
          </span>
        </div>
        {overview.patients.length === 0 ? (
          <EmptyRoster />
        ) : (
          <div className="overflow-hidden rounded-[6px] border border-rule bg-panel">
            {overview.patients.map((patient, index) => (
              <PatientRow
                key={patient.treatment_id}
                patient={patient}
                onSelect={onSelect}
                isLast={index === overview.patients.length - 1}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** One figure in the executive snapshot. The caption says what the number
 * counts — "need attention" in particular is otherwise a threshold the
 * reader has to guess at, and it is simply the backend's own rule. */
function Metric({
  label,
  value,
  caption,
  alert,
}: {
  label: string;
  value: number;
  caption: string;
  alert?: boolean;
}) {
  return (
    <div className="border-rule px-6 py-5 [&:not(:nth-child(2n+1))]:border-l sm:[&:not(:first-child)]:border-l">
      <div className="flex items-center gap-1.5">
        {alert && (
          <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-alert" aria-hidden />
        )}
        <div className="font-sans text-[12px] font-medium text-ink-mid">{label}</div>
      </div>
      <div
        className={`readout mt-1.5 text-[40px] font-semibold leading-none ${
          alert ? "text-alert" : "text-ink"
        }`}
      >
        {value}
      </div>
      <div className="mt-1.5 text-[11px] leading-snug text-ink-faint">{caption}</div>
    </div>
  );
}

function PatientRow({
  patient,
  onSelect,
  isLast,
}: {
  patient: OverviewPatient;
  onSelect: (patientId: string) => void;
  isLast: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(patient.patient_id)}
      className={`flex w-full gap-4 text-left hover:bg-band/60 ${
        isLast ? "" : "border-b border-rule"
      }`}
    >
      <RiskRail level={patient.risk_level} />

      <div className="min-w-0 flex-1 py-3 pr-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <div className="text-[14px] font-medium">{patient.patient_id}</div>
            <div className="mt-0.5 text-[11px] text-ink-mid">
              {patient.drug_name} · dose {patient.dose_count} ·{" "}
              {patient.treatment_status.toLowerCase()}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {patient.gated && (
              <span
                className="border border-rule-strong px-1.5 py-0.5 text-[9px] tracking-[0.1em] text-ink-mid"
                title="The data-quality gate overrode the risk model"
              >
                GATED
              </span>
            )}
            <RiskToken level={patient.risk_level} />
            {patient.next_dose && <DoseToken decision={patient.next_dose} />}
          </div>
        </div>
      </div>
    </button>
  );
}

function EmptyRoster() {
  return (
    <div className="border border-dashed border-rule-strong bg-panel p-8 text-center">
      <div className="eyebrow mb-2">No patients enrolled</div>
      <p className="mx-auto max-w-md font-sans text-[13px] leading-relaxed text-ink-mid">
        Screen a patient in Phase 1 and register a treatment, or load the
        synthetic demonstration cohort to populate the board.
      </p>
    </div>
  );
}
