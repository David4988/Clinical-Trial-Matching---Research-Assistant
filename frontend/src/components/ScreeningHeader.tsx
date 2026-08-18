import type { HeuristicFlag, ScreeningResult } from "../types/canonical";
import { OverallBanner } from "./Verdict";

export function ScreeningHeader({ result }: { result: ScreeningResult }) {
  const { patient, trial } = result;

  return (
    <section className="space-y-4">
      <div className="grid gap-4 border border-rule bg-panel p-4 sm:grid-cols-2">
        <div>
          <div className="eyebrow mb-1">Candidate</div>
          <div className="readout text-[24px] font-semibold leading-none">
            {patient.patient_id}
          </div>
          <div className="mt-1.5 font-sans text-[13px] text-ink-mid">
            {[
              patient.age !== null ? `${patient.age} years` : "age not recorded",
              patient.sex !== "UNKNOWN" ? patient.sex.toLowerCase() : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
        <div className="sm:border-l sm:border-rule sm:pl-4">
          <div className="eyebrow mb-1">Screened against</div>
          <div className="readout text-[24px] font-semibold leading-none">
            {trial.trial_id}
          </div>
          <div className="mt-1.5 font-sans text-[13px] leading-snug text-ink-mid">
            {trial.title}
          </div>
        </div>
      </div>

      <OverallBanner status={result.overall_status} reason={result.status_reason} />

      <Tallies result={result} />

      {result.heuristic_flags.length > 0 && (
        <HeuristicList flags={result.heuristic_flags} />
      )}
    </section>
  );
}

function Tallies({ result }: { result: ScreeningResult }) {
  const items = [
    { label: "Pass", value: result.passed_count, safe: result.passed_count > 0 },
    { label: "Fail", value: result.failed_count, alert: result.failed_count > 0 },
    { label: "Unknown", value: result.unknown_count, hatched: result.unknown_count > 0 },
    {
      label: "Rule coverage",
      value: `${Math.round(result.rule_coverage * 100)}%`,
      hint: "criteria the deterministic engine could verify",
    },
  ];

  return (
    // gap-px over a rule-coloured ground draws the hairlines, so they stay
    // correct however the grid wraps.
    <div className="stagger grid grid-cols-2 gap-px border border-rule bg-rule sm:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="bg-panel p-3">
          <div className="flex items-center gap-1.5">
            {item.hatched && <span className="hatch inline-block h-2.5 w-2.5" />}
            {item.alert && <span className="inline-block h-2.5 w-2.5 bg-alert" />}
            {item.safe && <span className="inline-block h-2.5 w-2.5 bg-safe" />}
            <div className="eyebrow">{item.label}</div>
          </div>
          <div
            className={`readout mt-1 text-[26px] font-semibold leading-none ${
              item.alert ? "text-alert" : item.safe ? "text-safe" : "text-ink"
            }`}
          >
            {item.value}
          </div>
          {item.hint && (
            <div className="mt-0.5 font-sans text-[11px] leading-tight text-ink-faint">
              {item.hint}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function HeuristicList({ flags }: { flags: HeuristicFlag[] }) {
  return (
    <section>
      <h2 className="eyebrow mb-2">Data quality notes</h2>
      <ul className="border border-rule bg-panel">
        {flags.map((flag, index) => (
          <li
            key={`${flag.code}-${index}`}
            className={`flex gap-3 p-3 ${index > 0 ? "border-t border-rule" : ""}`}
          >
            <span
              className={`mt-1 h-2 w-2 shrink-0 ${
                flag.severity === "WARN" ? "bg-ink" : "border border-ink-faint"
              }`}
            />
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-[11px] font-medium">{flag.code}</span>
                <span className="text-[10px] tracking-[0.1em] text-ink-faint">
                  {flag.severity}
                </span>
              </div>
              <p className="mt-0.5 font-sans text-[13px] leading-relaxed text-ink-mid">
                {flag.message}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
