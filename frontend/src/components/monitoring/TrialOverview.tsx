import type { OverviewPatient, RiskLevel, TrialOverview } from "../../types/monitoring";
import { DoseToken, RiskChip, RiskRail, RiskToken } from "./RiskMark";

/**
 * The board: how many patients, at what risk, and who needs looking at first.
 *
 * "Requiring attention" leads because it is the only part that prompts action.
 * The full roster sits underneath for context.
 */

const LEVELS: RiskLevel[] = ["GREEN", "AMBER", "RED", "UNKNOWN"];

export function TrialOverviewView({
  overview,
  onSelect,
}: {
  overview: TrialOverview;
  onSelect: (patientId: string) => void;
}) {
  return (
    <section className="space-y-6">
      <div className="border border-rule bg-panel p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <div className="eyebrow mb-1">Trial</div>
            <div className="text-lg font-medium">{overview.trial_id}</div>
          </div>
          <div className="text-right">
            <div className="eyebrow mb-1">Protocol</div>
            <div className="text-[12px] text-ink-mid">{overview.protocol_id}</div>
          </div>
        </div>

        <p className="mt-3 border-l-2 border-caution/50 bg-caution-wash pl-3 py-1.5 font-sans text-[12px] leading-relaxed text-ink-mid">
          {overview.protocol_label}. Every threshold in this view is synthetic and
          exists to demonstrate the pipeline — it is not clinical guidance.
        </p>

        <div className="mt-4 grid grid-cols-2 gap-4 border-t border-rule pt-4 sm:grid-cols-4">
          <Tally label="Patients" value={overview.total_patients} />
          <Tally label="Active treatments" value={overview.active_treatments} />
          <Tally
            label="Need attention"
            value={overview.requiring_attention.length}
            alert={overview.requiring_attention.length > 0}
          />
          <Tally
            label="Unassessable"
            value={overview.risk_counts.UNKNOWN ?? 0}
            hint="data not trustworthy"
          />
        </div>

        <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-rule pt-4">
          {LEVELS.map((level) => (
            <RiskChip key={level} level={level} count={overview.risk_counts[level] ?? 0} />
          ))}
        </div>
      </div>

      {overview.requiring_attention.length > 0 && (
        <div>
          <h2 className="eyebrow mb-2">
            Requiring attention ({overview.requiring_attention.length})
          </h2>
          <div className="border border-rule bg-panel">
            {overview.requiring_attention.map((patient, index) => (
              <PatientRow
                key={patient.patient_id}
                patient={patient}
                onSelect={onSelect}
                isLast={index === overview.requiring_attention.length - 1}
              />
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="eyebrow">All patients</h2>
          <span className="text-[11px] text-ink-faint">
            {overview.patients.length} enrolled
          </span>
        </div>
        {overview.patients.length === 0 ? (
          <EmptyRoster />
        ) : (
          <div className="border border-rule bg-panel">
            {overview.patients.map((patient, index) => (
              <PatientRow
                key={patient.patient_id}
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

function Tally({
  label,
  value,
  alert,
  hint,
}: {
  label: string;
  value: number;
  alert?: boolean;
  hint?: string;
}) {
  return (
    <div>
      <div className="eyebrow mb-0.5">{label}</div>
      <div
        className={`text-2xl font-medium tabular-nums ${alert ? "text-alert" : "text-ink"}`}
      >
        {value}
      </div>
      {hint && <div className="text-[10px] text-ink-faint">{hint}</div>}
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
