import type {
  MeasurementSummary,
  MonitoringCycleResult,
  RiskLevel,
  XAIExplanationRequest,
  XAIExplanation,
} from "../../types/monitoring";
import { useEffect, useState } from "react";
import { TrajectoryChart } from "./TrajectoryChart";
import { DoseToken, RiskRail, TrendMark } from "./RiskMark";

/**
 * One participant's console.
 *
 * The composition is the argument. A reader arriving here should take the
 * state from the top band without reading a word, watch it happen on the
 * trajectory, and only then meet the two columns that explain it: what the
 * model saw on the left, what the protocol did on the right. Those two sit
 * side by side and are typed differently on purpose — advisory against
 * authoritative — because the product rests on them not being the same kind
 * of statement.
 */

const LABELS: Record<string, string> = {
  HEART_RATE: "Heart rate",
  SYSTOLIC_BP: "Systolic BP",
  DIASTOLIC_BP: "Diastolic BP",
  SPO2: "SpO₂",
  TEMPERATURE: "Temperature",
  RESPIRATORY_RATE: "Resp. rate",
};

/** How loudly each state is allowed to speak. */
const HERO: Record<RiskLevel, { shell: string; edge: string; text: string }> = {
  GREEN: { shell: "border-rule bg-panel", edge: "bg-safe", text: "text-safe" },
  AMBER: {
    shell: "border-caution/45 bg-caution-wash",
    edge: "stripe-caution",
    text: "text-caution",
  },
  RED: { shell: "border-alert/50 bg-alert-wash", edge: "bg-alert", text: "text-alert" },
  UNKNOWN: { shell: "border-rule-strong bg-panel", edge: "hatch", text: "text-ink-mid" },
};

export function PatientMonitor({ cycle }: { cycle: MonitoringCycleResult }) {
  const { state, effective_risk } = cycle;

  return (
    <div className="space-y-5">
      <RiskHero cycle={cycle} />

      {effective_risk.gated && <GateNotice cycle={cycle} />}

      <Trajectory cycle={cycle} />

      <div className="grid gap-5 lg:grid-cols-[1.02fr_1fr]">
        <Signals cycle={cycle} />
        <Response cycle={cycle} />
      </div>

      <Vitals state={state} />

      <p className="border-t border-rule pt-3 font-sans text-[11px] leading-relaxed text-ink-faint">
        Risk is advisory. Every action shown here comes from the deterministic
        protocol table, and the next-dose result is decision support for a
        clinician — nothing in this system administers treatment.
      </p>
    </div>
  );
}

/**
 * The band that answers everything at a glance: who, what state, whether it
 * moved, and what the protocol wants done about it.
 */
function RiskHero({ cycle }: { cycle: MonitoringCycleResult }) {
  const { state, effective_risk, next_dose, transition, risk } = cycle;
  const treatment = state.treatment;
  const latestDose = treatment?.doses[treatment.doses.length - 1];
  const tone = HERO[effective_risk.level];

  return (
    <section className={`animate-rise border ${tone.shell}`}>
      <div className={`h-1 ${tone.edge}`} />

      <div className="grid gap-x-8 gap-y-6 p-5 lg:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="eyebrow">Participant under monitoring</div>
          <div className="readout mt-1 text-[34px] font-semibold leading-none">
            {cycle.patient_id}
          </div>
          <div className="mt-2 font-sans text-[12.5px] leading-relaxed text-ink-mid">
            {cycle.trial_id}
            {treatment && ` · ${treatment.drug_name}`}
            {latestDose &&
              ` · dose ${latestDose.dose_number}, ${latestDose.amount} ${latestDose.unit}`}
            {` · ${state.observation_count} observations`}
          </div>

          <p className="mt-3 max-w-xl font-sans text-[13px] leading-relaxed text-ink">
            {cycle.summary}
          </p>
        </div>

        {/* The state itself, at the scale of the thing it is. */}
        <div className="lg:border-l lg:border-rule lg:pl-8">
          <div className="eyebrow">Current risk</div>
          <div
            key={effective_risk.level}
            className="animate-state mt-1 flex items-center gap-3"
          >
            <span className={`h-9 w-2.5 shrink-0 ${tone.edge}`} aria-hidden />
            <span className={`readout text-[46px] font-semibold leading-none ${tone.text}`}>
              {effective_risk.level}
            </span>
          </div>

          <div className="mt-3">
            {transition ? (
              <span className="inline-flex items-center gap-2 text-[12px]">
                <span className="readout text-ink-mid">
                  {transition.from_level ?? "first read"}
                </span>
                <span aria-hidden className="text-signal-deep">→</span>
                <span className="readout font-semibold">{transition.to_level}</span>
                <span className="text-ink-faint">this cycle</span>
              </span>
            ) : (
              <span className="text-[12px] text-ink-faint">unchanged this cycle</span>
            )}
          </div>

          <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-rule pt-3">
            <Readout label="Score" value={risk.score.toFixed(2)} />
            <Readout label="Confidence" value={risk.confidence.toFixed(2)} />
            {next_dose && (
              <div>
                <dt className="text-[10px] tracking-[0.08em] text-ink-faint">NEXT DOSE</dt>
                <dd className="mt-1">
                  <DoseToken decision={next_dose.decision} />
                </dd>
              </div>
            )}
          </dl>

          {cycle.early_warning && (
            <div className="mt-5 border-t border-rule pt-4">
              <div className="eyebrow text-signal-deep">3h Early Warning</div>
              {cycle.early_warning.data_quality_state !== "OK" ? (
                <div className="mt-2 text-[12px] text-ink-mid">
                  Early warning unavailable
                  <br />
                  Insufficient observations
                </div>
              ) : (
                <EarlyWarningExplainable cycle={cycle} />
              )}
            </div>
          )}
        </div>
      </div>

      {treatment?.override && (
        <div className="flex gap-3 border-t border-rule/70 px-5 py-2.5">
          <span className="mt-0.5 h-3 w-3 shrink-0 stripe-caution" aria-hidden />
          <p className="font-sans text-[12px] leading-relaxed text-ink">
            <span className="font-semibold">Enrolled on override.</span>{" "}
            {treatment.override.approved_by} approved despite{" "}
            <span className="readout">{treatment.override.screening_status}</span>:{" "}
            {treatment.override.reason}
          </p>
        </div>
      )}
    </section>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] tracking-[0.08em] text-ink-faint">
        {label.toUpperCase()}
      </dt>
      <dd className="readout mt-0.5 text-[18px] font-medium leading-none">{value}</dd>
    </div>
  );
}

function EarlyWarningExplainable({ cycle }: { cycle: MonitoringCycleResult }) {
  const [explanation, setExplanation] = useState<XAIExplanation | null>(null);
  const [loading, setLoading] = useState(true);
  const ew = cycle.early_warning!;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setExplanation(null);
    
    // Only fetch explanation if it's elevated, or based on product rules. 
    // Usually XAI adds most value when there's an anomaly.
    // For demonstration, we'll fetch it anytime ew is available and score is not null.

    if (ew.score === null) {
      setLoading(false);
      return;
    }

    const req: XAIExplanationRequest = {
      model_name: ew.provider,
      model_version: ew.model_version,
      signal_type: "EARLY_WARNING",
      risk_state: ew.predicted_deterioration ? "ELEVATED" : "LOW",
      score: ew.score,
      score_semantics: "RISK_SCORE",
      horizon_hours: ew.horizon_hours,
      // Map evidence features to generic dictionaries
      evidence: ew.evidence.map((e) => ({
        feature_name: e.feature_name,
        contribution: e.contribution,
        direction: e.direction,
        raw_value: e.raw_value,
        transformed_value: e.transformed_value,
        objective_description: e.objective_description
      })),
      // Fallback deterministic explanation
      deterministic_explanation: "Early warning score evaluated based on recent observation deltas."
    };

    fetch("/api/monitoring/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req)
    })
      .then((r) => r.json())
      .then((res: XAIExplanation) => {
        if (active) {
          setExplanation(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        console.error("XAI request failed", err);
        if (active) setLoading(false);
      });

    return () => { active = false; };
  }, [ew.artifact_checksum, ew.evaluated_at]);

  return (
    <div className="mt-2 space-y-4">
      <div className="flex items-center gap-3">
        <span className={`readout text-[28px] font-semibold leading-none ${ew.predicted_deterioration ? 'text-alert' : 'text-safe'}`}>
          {ew.predicted_deterioration ? "ELEVATED" : "LOW"}
        </span>
        <dl className="flex gap-4 ml-4">
          <Readout label="Risk Score" value={ew.score?.toFixed(2) ?? "—"} />
          <Readout label="Horizon" value={`${ew.horizon_hours}h`} />
        </dl>
      </div>

      <div className="bg-panel border border-rule mt-4 p-4 text-sm font-sans space-y-3">
        <div>
          <div className="eyebrow mb-1">AI INTERPRETATION (ADVISORY)</div>
          {loading ? (
             <div className="animate-pulse flex space-x-4">
                <div className="flex-1 space-y-2 py-1">
                  <div className="h-2 bg-rule rounded"></div>
                  <div className="h-2 bg-rule rounded w-5/6"></div>
                </div>
             </div>
          ) : explanation ? (
             <div className="text-ink-mid leading-relaxed">
               {explanation.explanation_text}
             </div>
          ) : (
             <div className="text-ink-faint">Explanation unavailable.</div>
          )}
        </div>

        <div className="pt-2 border-t border-rule-strong">
          <div className="eyebrow mb-1">MODEL EVIDENCE</div>
          <div className="space-y-1">
            {ew.evidence.map((ev, i) => (
              <div key={i} className="text-[11.5px] text-ink-mid">
                • {ev.objective_description}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Trajectory({ cycle }: { cycle: MonitoringCycleResult }) {
  return (
    <section>
      <SectionHead
        title="Trajectory"
        note="every vital on one clock, with the events that happened to them"
      />
      <div className="border border-rule bg-panel p-4">
        <TrajectoryChart
          observations={cycle.state.recent_observations}
          doses={cycle.state.treatment?.doses ?? []}
          interventions={cycle.interventions}
          transition={cycle.transition}
          riskLevel={cycle.effective_risk.level}
        />
      </div>
    </section>
  );
}

/** Left column: what the model saw. Advisory, and typed as such. */
function Signals({ cycle }: { cycle: MonitoringCycleResult }) {
  const { risk } = cycle;

  return (
    <section className="flex flex-col">
      <SectionHead
        title="Signals"
        authority="MODEL · ADVISORY"
        tone="signal"
        note={`${risk.provider} @ ${risk.model_version}`}
      />

      <div className="flex-1 border border-rule bg-panel p-4">
        {risk.contributing_factors.length > 0 ? (
          <ul className="stagger space-y-3">
            {risk.contributing_factors.map((factor, index) => (
              <li key={index} className="text-[12px] leading-relaxed">
                <div className="flex items-center gap-3">
                  <span className="min-w-[8rem] text-[11px] tracking-[0.06em]">
                    {factor.factor.replace(/_/g, " ").toLowerCase()}
                  </span>
                  <span
                    className="h-1.5 flex-1 bg-band"
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
                  <span className="readout w-9 text-right text-[11px] text-ink-mid">
                    {factor.weight.toFixed(2)}
                  </span>
                </div>
                <p className="mt-1 font-sans text-ink-mid">{factor.detail}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="font-sans text-[12px] text-ink-mid">
            The model reported no contributing factors for this window.
          </p>
        )}

        {risk.likely_patterns.length > 0 && (
          <div className="mt-4 border-l-2 border-signal/40 py-2 pl-3">
            {risk.likely_patterns.map((pattern, index) => (
              <p
                key={index}
                className="font-sans text-[11.5px] leading-relaxed text-ink-mid"
              >
                {pattern}
              </p>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** Right column: what the protocol did about it. Authoritative. */
function Response({ cycle }: { cycle: MonitoringCycleResult }) {
  const cadence = cycle.interventions.find(
    (i) => i.monitoring_interval_minutes !== null,
  );

  return (
    <section className="flex flex-col">
      <SectionHead
        title="Protocol response"
        authority="DETERMINISTIC · AUTHORITATIVE"
        note={
          cadence
            ? `monitoring every ${cadence.monitoring_interval_minutes} min`
            : undefined
        }
      />

      <div className="flex-1 border border-rule bg-panel">
        {cycle.interventions.length === 0 ? (
          <p className="p-4 font-sans text-[12px] text-ink-mid">
            The protocol required no action at this level.
          </p>
        ) : (
          <ul className="stagger">
            {cycle.interventions.map((intervention, index) => (
              <li
                key={intervention.intervention_id}
                className={index === 0 ? "" : "border-t border-rule"}
              >
                <div className="flex gap-3 p-3">
                  <RiskRail level={intervention.risk_level} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-sans text-[14px] font-semibold tracking-[-0.01em]">
                        {intervention.action.replace(/_/g, " ").toLowerCase()}
                      </span>
                      <span className="readout text-[10px] text-ink-faint">
                        {intervention.protocol_rule_id}
                      </span>
                    </div>
                    <p className="mt-1 font-sans text-[12px] leading-relaxed text-ink-mid">
                      {intervention.rationale}
                    </p>

                    <details className="group mt-1.5">
                      <summary className="inline-flex items-center gap-1.5 text-[11px] text-ink-mid hover:text-ink">
                        <span className="transition-transform duration-200 group-open:rotate-90">
                          ▸
                        </span>
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
                                <span className="readout text-[11px] text-ink-mid">
                                  {item.locator}
                                </span>
                              )}
                            </div>
                            {item.snippet && (
                              <div className="mt-0.5 text-ink">{item.snippet}</div>
                            )}
                            {item.note && (
                              <div className="mt-0.5 font-sans text-ink-mid">{item.note}</div>
                            )}
                          </li>
                        ))}
                      </ol>
                    </details>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}

        {cycle.notifications.length > 0 && (
          <div className="animate-rise border-t border-rule bg-band/40 p-3">
            <div className="eyebrow mb-1.5">Sent ({cycle.notifications.length})</div>
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

        {cycle.next_dose && <NextDose next={cycle.next_dose} />}
      </div>
    </section>
  );
}

function NextDose({ next }: { next: NonNullable<MonitoringCycleResult["next_dose"]> }) {
  return (
    <div className="border-t-2 border-ink/15 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="eyebrow">Next dose</span>
        <DoseToken decision={next.decision} />
        {next.proposed_dose_number !== null && (
          <span className="text-[12px] text-ink-mid">
            proposed dose {next.proposed_dose_number}
          </span>
        )}
        <span className="ml-auto text-[10px] text-ink-faint">decision support only</span>
      </div>

      {next.reasons.length > 0 && (
        <ul className="mt-2 space-y-1 font-sans text-[12px] leading-relaxed text-ink-mid">
          {next.reasons.map((reason, index) => (
            <li key={index}>{reason}</li>
          ))}
        </ul>
      )}

      <details className="group mt-2">
        <summary className="inline-flex items-center gap-1.5 text-[11px] text-ink-mid hover:text-ink">
          <span className="transition-transform duration-200 group-open:rotate-90">▸</span>
          Protocol criteria ({next.criteria.length})
        </summary>
        <ul className="mt-2 space-y-2">
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
                  <span className="readout text-[10px] text-ink-faint">
                    {criterion.criterion_id}
                  </span>
                  <span className="text-ink">{criterion.description}</span>
                </div>
                <div className="font-sans text-[11.5px] text-ink-mid">
                  {criterion.detail}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function Vitals({ state }: { state: MonitoringCycleResult["state"] }) {
  return (
    <section>
      <SectionHead
        title="Latest readings"
        note="baseline = this patient's own first readings"
      />

      {state.measurements.length === 0 ? (
        <div className="border border-dashed border-rule-strong bg-panel p-6 text-center text-[13px] text-ink-mid">
          No measurements recorded.
        </div>
      ) : (
        <div className="grid gap-px border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-3">
          {state.measurements.map((measurement) => (
            <VitalCell key={measurement.measurement_type} measurement={measurement} />
          ))}
        </div>
      )}

      {state.data_quality.flags.length > 0 && (
        <div className="mt-3 border border-rule bg-panel p-3">
          <div className="eyebrow mb-1.5">Data quality · {state.data_quality.status}</div>
          <ul className="space-y-1 font-sans text-[12px] leading-relaxed text-ink-mid">
            {state.data_quality.flags.map((flag) => (
              <li key={flag.code}>
                <span className="readout text-[10px] tracking-[0.08em] text-ink-faint">
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

function VitalCell({ measurement }: { measurement: MeasurementSummary }) {
  const delta = measurement.delta_from_baseline;
  const moved = delta !== null && delta !== 0;

  return (
    <div className="bg-panel px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-sans text-[12px] text-ink-mid">
          {LABELS[measurement.measurement_type]}
        </span>
        <TrendMark trend={measurement.trend} />
      </div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className="readout text-[24px] font-semibold leading-none">
          {measurement.current ?? "—"}
        </span>
        <span className="text-[11px] text-ink-mid">{measurement.unit}</span>
      </div>
      <div className="mt-1.5 text-[10.5px] text-ink-faint">
        {moved ? `${delta > 0 ? "+" : ""}${delta} from baseline` : "no change"}
        {measurement.is_stale && " · stale"}
      </div>
    </div>
  );
}

function GateNotice({ cycle }: { cycle: MonitoringCycleResult }) {
  const { effective_risk } = cycle;
  return (
    <section className="animate-rise border border-rule-strong bg-panel">
      <div className="hatch h-1.5" />
      <div className="p-4">
        <div className="text-[10px] font-semibold tracking-[0.12em] text-ink">
          DATA-QUALITY GATE APPLIED
        </div>
        <p className="mt-1 font-sans text-[13px] leading-relaxed text-ink">
          The risk model reported{" "}
          <strong className="readout">{effective_risk.provider_level}</strong>, but the
          record could not support it. The applied level is{" "}
          <strong className="readout">{effective_risk.level}</strong>.
        </p>
        <p className="mt-1.5 font-sans text-[12px] leading-relaxed text-ink-mid">
          {effective_risk.reason}
        </p>
      </div>
    </section>
  );
}

/** One heading rule for the whole console, so the sections read as one system. */
function SectionHead({
  title,
  authority,
  tone = "ink",
  note,
}: {
  title: string;
  authority?: string;
  tone?: "ink" | "signal";
  note?: string;
}) {
  return (
    <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
      <div className="flex items-baseline gap-3">
        <h2 className="title text-[16px]">{title}</h2>
        {authority && (
          <span
            className={`text-[9.5px] font-semibold tracking-[0.12em] ${
              tone === "signal" ? "text-signal-deep" : "text-ink-faint"
            }`}
          >
            {authority}
          </span>
        )}
      </div>
      {note && <span className="text-[11px] text-ink-faint">{note}</span>}
    </div>
  );
}
