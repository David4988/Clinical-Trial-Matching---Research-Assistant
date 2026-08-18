import type {
  MeasurementSummary,
  MonitoringCycleResult,
  Observation,
} from "../../types/monitoring";
import { Sparkline } from "./Sparkline";
import {
  DoseToken,
  RiskDisplay,
  RiskRail,
  RiskToken,
  TrendMark,
} from "./RiskMark";

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
    <div className="space-y-7">
      <StatusHeader cycle={cycle} />

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

/**
 * The four questions a reader has on arrival, answered in one band: who is
 * this, what state are they in, is that state moving, and what does the
 * protocol require next. Everything below this is the evidence for it.
 */
function StatusHeader({ cycle }: { cycle: MonitoringCycleResult }) {
  const { state, effective_risk, next_dose, transition } = cycle;
  const treatment = state.treatment;
  const latestDose = treatment?.doses[treatment.doses.length - 1];

  return (
    <section className="animate-rise border border-rule bg-panel">
      <div className="border-b border-rule">
        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-5 p-4">
          <div className="min-w-[13rem]">
            <div className="eyebrow">Participant</div>
            <div className="readout text-[30px] font-semibold leading-none">
              {cycle.patient_id}
            </div>
            <div className="mt-2 font-sans text-[12px] leading-relaxed text-ink-mid">
              {cycle.trial_id}
              {treatment && ` · ${treatment.drug_name}`}
              {latestDose &&
                ` · dose ${latestDose.dose_number} of ${latestDose.amount} ${latestDose.unit}`}
              {` · ${state.observation_count} observations`}
            </div>
          </div>

          <div>
            <div className="eyebrow mb-1.5">Current state</div>
            {/* Keyed on the level so a change replays the arrival, and only then. */}
            <div key={effective_risk.level} className="animate-state">
              <RiskDisplay level={effective_risk.level} />
            </div>
            <div className="mt-2 text-[11px]">
              {transition ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="readout text-ink-mid">
                    {transition.from_level ?? "first assessment"}
                  </span>
                  <span aria-hidden className="text-signal-deep">→</span>
                  <span className="readout font-semibold">{transition.to_level}</span>
                  <span className="text-ink-faint">this cycle</span>
                </span>
              ) : (
                <span className="text-ink-faint">unchanged this cycle</span>
              )}
            </div>
          </div>

          <div className="min-w-[9rem]">
            <div className="eyebrow mb-1.5">Next dose</div>
            {next_dose ? (
              <>
                <DoseToken decision={next_dose.decision} />
                <div className="mt-2 text-[11px] text-ink-faint">
                  {next_dose.proposed_dose_number !== null
                    ? `proposed dose ${next_dose.proposed_dose_number}`
                    : "no dose proposed"}
                </div>
              </>
            ) : (
              <div className="text-[12px] text-ink-faint">not assessed</div>
            )}
          </div>
        </div>
      </div>

      {treatment?.override && (
        <div className="flex gap-3 border-b border-rule bg-caution-wash px-4 py-2.5">
          <span className="mt-0.5 h-3 w-3 shrink-0 stripe-caution" aria-hidden />
          <p className="font-sans text-[12px] leading-relaxed text-ink">
            <span className="font-semibold text-caution">Enrolled on override.</span>{" "}
            {treatment.override.approved_by} approved despite{" "}
            <span className="readout">{treatment.override.screening_status}</span>:{" "}
            {treatment.override.reason}
          </p>
        </div>
      )}

      <p className="px-4 py-2.5 font-sans text-[12px] leading-relaxed text-ink-mid">
        {cycle.summary}
      </p>
    </section>
  );
}

/**
 * Section heading carrying the authority of what follows. The three tiers are
 * the real architecture of this product — a model that advises, a protocol
 * that decides, a person who acts — so the heading states which one is
 * speaking rather than leaving three identical panels to be told apart.
 */
function Tier({
  step,
  title,
  authority,
  tone = "ink",
  meta,
}: {
  step: string;
  title: string;
  authority: string;
  tone?: "ink" | "signal";
  meta?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-rule pb-2">
      <div className="flex items-baseline gap-3">
        <span className="readout text-[11px] text-ink-faint">{step}</span>
        <h2 className="title text-[17px]">{title}</h2>
        <span
          className={`text-[10px] font-semibold tracking-[0.12em] ${
            tone === "signal" ? "text-signal-deep" : "text-ink-faint"
          }`}
        >
          {authority}
        </span>
      </div>
      {meta && <span className="text-[11px] text-ink-faint">{meta}</span>}
    </div>
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
      <Tier
        step="01"
        title="What the record shows"
        authority="OBSERVED"
        meta="baseline = this patient's own first readings"
      />

      {state.measurements.length === 0 ? (
        <div className="border border-dashed border-rule-strong bg-panel p-6 text-center text-[13px] text-ink-mid">
          No measurements recorded.
        </div>
      ) : (
        <div className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {state.measurements.map((measurement) => (
            <VitalCard
              key={measurement.measurement_type}
              measurement={measurement}
              series={byType.get(measurement.measurement_type) ?? []}
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

function VitalCard({
  measurement,
  series,
}: {
  measurement: MeasurementSummary;
  series: Observation[];
}) {
  const delta = measurement.delta_from_baseline;
  const moved = delta !== null && delta !== 0;

  return (
    <div className="border border-rule bg-panel p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-sans text-[12px] font-medium">
          {LABELS[measurement.measurement_type]}
        </span>
        <TrendMark trend={measurement.trend} />
      </div>

      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="readout text-[26px] font-semibold leading-none">
          {measurement.current ?? "—"}
        </span>
        <span className="text-[11px] text-ink-mid">{measurement.unit}</span>
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <div className="text-[10px] tracking-[0.08em] text-ink-faint">
            FROM BASELINE
          </div>
          <div className="readout mt-0.5 text-[12px]">
            {moved ? `${delta > 0 ? "+" : ""}${delta}` : "no change"}
          </div>
        </div>
        <Sparkline observations={series} width={110} height={30} />
      </div>

      <div className="mt-2 text-[10px] text-ink-faint">
        {measurement.sample_count} readings
        {measurement.is_stale && " · stale"}
      </div>
    </div>
  );
}

function RiskPanel({ cycle }: { cycle: MonitoringCycleResult }) {
  const { risk, effective_risk, transition } = cycle;

  return (
    <section>
      <Tier
        step="02"
        title="What the model reports"
        authority="ADVISORY"
        tone="signal"
        meta={`${risk.provider} @ ${risk.model_version}`}
      />

      <div className="flex border border-rule bg-panel">
        <RiskRail level={effective_risk.level} />
        <div className="min-w-0 flex-1 p-4">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <RiskToken level={effective_risk.level} />
            <Metric label="score" value={risk.score.toFixed(2)} />
            <Metric label="confidence" value={risk.confidence.toFixed(2)} />
            <Metric label="horizon" value={`${risk.prediction_horizon_hours}h`} />
          </div>

          {transition && (
            <p className="mt-2.5 font-sans text-[13px] leading-relaxed text-ink">
              {transition.trigger}
            </p>
          )}

          {risk.contributing_factors.length > 0 && (
            <div className="mt-3">
              <div className="eyebrow mb-1.5">Contributing factors</div>
              <ul className="stagger space-y-2.5">
                {risk.contributing_factors.map((factor, index) => (
                  <li key={index} className="text-[12px] leading-relaxed">
                    <div className="flex items-center gap-3">
                      <span className="min-w-[8.5rem] text-[11px] tracking-[0.06em]">
                        {factor.factor.replace(/_/g, " ").toLowerCase()}
                      </span>
                      {/* The weight the model actually returned, drawn to
                          scale so the factors can be compared at a glance.
                          Teal: this is the model speaking, not a clinical
                          state. */}
                      <span
                        className="h-1.5 w-24 shrink-0 bg-band"
                        role="img"
                        aria-label={`weight ${factor.weight.toFixed(2)} of 1`}
                      >
                        <span
                          className="block h-full bg-signal"
                          style={{
                            width: `${Math.max(0, Math.min(1, factor.weight)) * 100}%`,
                          }}
                        />
                      </span>
                      <span className="readout text-[11px] text-ink-mid">
                        {factor.weight.toFixed(2)}
                      </span>
                    </div>
                    <div className="mt-0.5 font-sans text-ink-mid">{factor.detail}</div>
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

/** A single labelled number, so the three read as one instrument row. */
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-[10px] tracking-[0.08em] text-ink-faint">
        {label.toUpperCase()}
      </span>
      <span className="readout text-[14px] font-medium">{value}</span>
    </span>
  );
}

function Protocol({ cycle }: { cycle: MonitoringCycleResult }) {
  const cadence = cycle.interventions.find(
    (i) => i.monitoring_interval_minutes !== null,
  );

  return (
    <section>
      <Tier
        step="03"
        title="What the protocol requires"
        authority="AUTHORITATIVE"
        meta={
          cadence
            ? `monitoring every ${cadence.monitoring_interval_minutes} min`
            : undefined
        }
      />

      <div className="stagger border border-rule bg-panel">
        {cycle.interventions.map((intervention, index) => (
          <div
            key={intervention.intervention_id}
            className={index === cycle.interventions.length - 1 ? "" : "border-b border-rule"}
          >
            <div className="p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-sans text-[14px] font-semibold tracking-[-0.01em]">
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
        <div className="animate-rise mt-3 border border-rule bg-panel p-3">
          <div className="eyebrow mb-1.5">
            Notifications sent ({cycle.notifications.length})
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
      <Tier
        step="04"
        title="Whether the next dose can go ahead"
        authority="DECISION SUPPORT"
        meta="a clinician administers, never this system"
      />

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
                      ? "border-safe bg-safe"
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
