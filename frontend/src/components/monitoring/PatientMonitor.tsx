import type {
  MeasurementSummary,
  MonitoringCycleResult,
  Observation,
} from "../../types/monitoring";
import { Sparkline } from "./Sparkline";
import { DoseToken, RiskRail, RiskToken, TrendMark } from "./RiskMark";

/**
 * One patient's current picture: treatment, vitals and trends, the risk read,
 * what the protocol requires, and whether the next dose can go ahead.
 *
 * The ordering is the architecture made visible. Deterministic state first, the
 * model's advisory read second and explicitly labelled, the protocol's response
 * third. Where the trust gate overrode the model, both verdicts are shown.
 */

const LABELS: Record<string, string> = {
  HEART_RATE: "Heart rate",
  SYSTOLIC_BP: "Systolic BP",
  DIASTOLIC_BP: "Diastolic BP",
  SPO2: "SpO₂",
  TEMPERATURE: "Temperature",
  RESPIRATORY_RATE: "Resp. rate",
};

export function PatientMonitor({ cycle }: { cycle: MonitoringCycleResult }) {
  const { state, effective_risk, next_dose } = cycle;

  return (
    <div className="space-y-6">
      <Identity cycle={cycle} />

      {effective_risk.gated && <GateNotice cycle={cycle} />}

      <Vitals state={state} />

      <RiskPanel cycle={cycle} />

      <Protocol cycle={cycle} />

      {next_dose && <NextDose next={next_dose} />}

      <p className="border-t border-rule pt-3 font-sans text-[11px] leading-relaxed text-ink-faint">
        Risk is advisory. Every action shown here comes from the deterministic
        protocol table, and the next-dose result is decision support for a
        clinician — nothing in this system administers treatment.
      </p>
    </div>
  );
}

function Identity({ cycle }: { cycle: MonitoringCycleResult }) {
  const treatment = cycle.state.treatment;
  const latestDose = treatment?.doses[treatment.doses.length - 1];

  return (
    <section className="grid gap-4 border border-rule bg-panel p-4 sm:grid-cols-2">
      <div>
        <div className="eyebrow mb-1">Patient</div>
        <div className="text-lg font-medium">{cycle.patient_id}</div>
        <div className="mt-0.5 text-[12px] text-ink-mid">
          Trial {cycle.trial_id} · {cycle.state.observation_count} observations
        </div>
      </div>
      <div className="sm:border-l sm:border-rule sm:pl-4">
        <div className="eyebrow mb-1">Treatment</div>
        {treatment ? (
          <>
            <div className="text-lg font-medium">{treatment.drug_name}</div>
            <div className="mt-0.5 text-[12px] text-ink-mid">
              {latestDose
                ? `Dose ${latestDose.dose_number} · ${latestDose.amount} ${latestDose.unit}`
                : "No dose administered yet"}{" "}
              · {treatment.status.toLowerCase()}
            </div>
            {treatment.override && (
              <div className="mt-2 border border-caution/40 bg-caution-wash p-2 text-[11px] leading-relaxed">
                <span className="font-semibold text-caution">ENROLLED ON OVERRIDE</span>
                <div className="mt-0.5 text-ink-mid">
                  {treatment.override.approved_by} approved despite{" "}
                  {treatment.override.screening_status}: {treatment.override.reason}
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="text-[13px] text-ink-faint">No treatment registered</div>
        )}
      </div>
    </section>
  );
}

function GateNotice({ cycle }: { cycle: MonitoringCycleResult }) {
  const { effective_risk } = cycle;
  return (
    <section className="border border-rule-strong bg-panel">
      <div className="hatch h-1.5" />
      <div className="p-4">
        <div className="text-[10px] font-semibold tracking-[0.12em] text-ink">
          DATA-QUALITY GATE APPLIED
        </div>
        <p className="mt-1 font-sans text-[13px] leading-relaxed text-ink">
          The risk model reported{" "}
          <strong className="font-mono">{effective_risk.provider_level}</strong>, but
          the record could not support it. The applied level is{" "}
          <strong className="font-mono">{effective_risk.level}</strong>.
        </p>
        <p className="mt-1.5 font-sans text-[12px] leading-relaxed text-ink-mid">
          {effective_risk.reason}
        </p>
      </div>
    </section>
  );
}

function Vitals({ state }: { state: MonitoringCycleResult["state"] }) {
  const byType = new Map<string, Observation[]>();
  for (const observation of state.recent_observations) {
    const list = byType.get(observation.measurement_type) ?? [];
    list.push(observation);
    byType.set(observation.measurement_type, list);
  }

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="eyebrow">Current vitals and trend</h2>
        <span className="text-[11px] text-ink-faint">
          baseline = this patient's own first readings
        </span>
      </div>

      {state.measurements.length === 0 ? (
        <div className="border border-dashed border-rule-strong bg-panel p-6 text-center text-[13px] text-ink-mid">
          No measurements recorded.
        </div>
      ) : (
        <div className="border border-rule bg-panel">
          {state.measurements.map((measurement, index) => (
            <VitalRow
              key={measurement.measurement_type}
              measurement={measurement}
              series={byType.get(measurement.measurement_type) ?? []}
              isLast={index === state.measurements.length - 1}
            />
          ))}
        </div>
      )}

      {state.data_quality.flags.length > 0 && (
        <div className="mt-3 border border-rule bg-panel p-3">
          <div className="eyebrow mb-1.5">
            Data quality · {state.data_quality.status}
          </div>
          <ul className="space-y-1 font-sans text-[12px] leading-relaxed text-ink-mid">
            {state.data_quality.flags.map((flag) => (
              <li key={flag.code}>
                <span className="font-mono text-[10px] tracking-[0.08em] text-ink-faint">
                  {flag.severity}
                </span>{" "}
                {flag.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function VitalRow({
  measurement,
  series,
  isLast,
}: {
  measurement: MeasurementSummary;
  series: Observation[];
  isLast: boolean;
}) {
  const delta = measurement.delta_from_baseline;
  return (
    <div
      className={`flex flex-wrap items-center gap-x-4 gap-y-2 p-3 ${
        isLast ? "" : "border-b border-rule"
      }`}
    >
      <div className="min-w-[9rem] flex-1">
        <div className="text-[13px]">{LABELS[measurement.measurement_type]}</div>
        <div className="mt-0.5 text-[10px] text-ink-faint">
          {measurement.sample_count} readings
          {measurement.is_stale && " · stale"}
        </div>
      </div>

      <div className="tabular-nums">
        <span className="text-[18px] font-medium">
          {measurement.current ?? "—"}
        </span>
        <span className="ml-1 text-[11px] text-ink-mid">{measurement.unit}</span>
      </div>

      <div className="flex min-w-[5.5rem] items-center gap-1.5">
        <TrendMark trend={measurement.trend} />
        <span className="text-[11px] tabular-nums text-ink-mid">
          {delta === null ? "" : `${delta > 0 ? "+" : ""}${delta}`}
        </span>
      </div>

      <Sparkline observations={series} />
    </div>
  );
}

function RiskPanel({ cycle }: { cycle: MonitoringCycleResult }) {
  const { risk, effective_risk, transition } = cycle;

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="eyebrow">Risk assessment · advisory</h2>
        <span className="text-[11px] text-ink-faint">
          {risk.provider} @ {risk.model_version}
        </span>
      </div>

      <div className="flex border border-rule bg-panel">
        <RiskRail level={effective_risk.level} />
        <div className="min-w-0 flex-1 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <RiskToken level={effective_risk.level} />
            <span className="text-[12px] text-ink-mid tabular-nums">
              score {risk.score.toFixed(2)} · confidence {risk.confidence.toFixed(2)}
            </span>
            <span className="text-[11px] text-ink-faint">
              horizon {risk.prediction_horizon_hours}h
            </span>
          </div>

          {transition && (
            <p className="mt-2 font-sans text-[12px] text-ink-mid">
              {transition.trigger}
            </p>
          )}

          {risk.contributing_factors.length > 0 && (
            <div className="mt-3">
              <div className="eyebrow mb-1.5">Contributing factors</div>
              <ul className="space-y-1.5">
                {risk.contributing_factors.map((factor, index) => (
                  <li key={index} className="text-[12px] leading-relaxed">
                    <div className="flex items-baseline gap-2">
                      <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                        {factor.factor}
                      </span>
                      <span className="text-[10px] tabular-nums text-ink-faint">
                        {factor.weight.toFixed(2)}
                      </span>
                    </div>
                    <div className="font-sans text-ink-mid">{factor.detail}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {risk.likely_patterns.length > 0 && (
            <div className="mt-3 border-l-2 border-rule-strong pl-3">
              {risk.likely_patterns.map((pattern, index) => (
                <p
                  key={index}
                  className="font-sans text-[12px] leading-relaxed text-ink-faint"
                >
                  {pattern}
                </p>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function Protocol({ cycle }: { cycle: MonitoringCycleResult }) {
  const cadence = cycle.interventions.find(
    (i) => i.monitoring_interval_minutes !== null,
  );

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="eyebrow">Protocol response · authoritative</h2>
        {cadence && (
          <span className="text-[11px] text-ink-faint">
            monitoring every {cadence.monitoring_interval_minutes} min
          </span>
        )}
      </div>

      <div className="border border-rule bg-panel">
        {cycle.interventions.map((intervention, index) => (
          <div
            key={intervention.intervention_id}
            className={index === cycle.interventions.length - 1 ? "" : "border-b border-rule"}
          >
            <div className="p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13px] font-medium">
                  {intervention.action.replace(/_/g, " ").toLowerCase()}
                </span>
                <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                  {intervention.protocol_rule_id}
                </span>
              </div>
              <p className="mt-1 font-sans text-[12px] leading-relaxed text-ink-mid">
                {intervention.rationale}
              </p>

              <details className="mt-2 group">
                <summary className="inline-flex items-center gap-1.5 text-[11px] text-ink-mid hover:text-ink">
                  <span className="transition-transform group-open:rotate-90">▸</span>
                  Evidence ({intervention.evidence.length})
                </summary>
                <ol className="mt-2 space-y-2 border-l border-rule pl-3">
                  {intervention.evidence.map((item, i) => (
                    <li key={i} className="text-[12px] leading-relaxed">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                          {item.source_type}
                        </span>
                        {item.locator && (
                          <span className="text-[11px] text-ink-mid">{item.locator}</span>
                        )}
                      </div>
                      {item.snippet && <div className="mt-0.5 text-ink">{item.snippet}</div>}
                      {item.note && (
                        <div className="mt-0.5 font-sans text-ink-mid">{item.note}</div>
                      )}
                    </li>
                  ))}
                </ol>
              </details>
            </div>
          </div>
        ))}
      </div>

      {cycle.notifications.length > 0 && (
        <div className="mt-3 border border-rule bg-panel p-3">
          <div className="eyebrow mb-1.5">
            Notifications generated ({cycle.notifications.length})
          </div>
          <ul className="space-y-1.5">
            {cycle.notifications.map((notification) => (
              <li key={notification.notification_id} className="text-[12px]">
                <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                  {notification.audience} · {notification.channel}
                  {notification.delivered_at ? " · delivered" : " · queued"}
                </span>
                <div className="text-ink">{notification.subject}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function NextDose({ next }: { next: MonitoringCycleResult["next_dose"] }) {
  if (!next) return null;

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="eyebrow">Next-dose assessment</h2>
        <span className="text-[11px] text-ink-faint">decision support only</span>
      </div>

      <div className="border border-rule bg-panel p-4">
        <div className="flex flex-wrap items-center gap-3">
          <DoseToken decision={next.decision} />
          {next.proposed_dose_number !== null && (
            <span className="text-[12px] text-ink-mid">
              proposed dose {next.proposed_dose_number}
            </span>
          )}
        </div>

        {next.reasons.length > 0 && (
          <ul className="mt-3 space-y-1 font-sans text-[12px] leading-relaxed text-ink-mid">
            {next.reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        )}

        <div className="mt-3 border-t border-rule pt-3">
          <div className="eyebrow mb-2">Protocol criteria</div>
          <ul className="space-y-2">
            {next.criteria.map((criterion) => (
              <li key={criterion.criterion_id} className="flex gap-3 text-[12px]">
                <span
                  className={`mt-0.5 inline-block h-2.5 w-2.5 shrink-0 border ${
                    criterion.satisfied === true
                      ? "border-ink bg-ink"
                      : criterion.satisfied === false
                        ? "border-alert bg-alert"
                        : "hatch border-rule-strong"
                  }`}
                  aria-hidden
                />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                      {criterion.criterion_id}
                    </span>
                    <span className="text-ink">{criterion.description}</span>
                    {criterion.satisfied === null && (
                      <span className="text-[10px] tracking-[0.08em] text-ink-mid">
                        NOT EVALUABLE
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 font-sans text-ink-mid">{criterion.detail}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
