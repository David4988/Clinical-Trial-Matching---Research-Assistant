import type { HeuristicFlag, ScreeningResult } from "../types/canonical";
import { OverallBanner } from "./Verdict";

/**
 * The left rail of the review workspace: who was screened, what the engine
 * concluded, and how much of the protocol it could actually verify.
 *
 * This is the column a reader returns to while reading the ledger, so it is
 * built to stay put and to be read top to bottom: identity, verdict, the
 * count behind the verdict, then anything the record itself made difficult.
 */
export function ScreeningHeader({ result }: { result: ScreeningResult }) {
  const { patient, trial } = result;

  return (
    <div className="space-y-4">
      <div className="border border-rule bg-panel">
        <div className="border-b border-rule p-4">
          <div className="eyebrow">Candidate</div>
          <div className="readout mt-1 text-[26px] font-semibold leading-none">
            {patient.patient_id}
          </div>
          <div className="mt-1.5 font-sans text-[12.5px] text-ink-mid">
            {[
              patient.age !== null ? `${patient.age} years` : "age not recorded",
              patient.sex !== "UNKNOWN" ? patient.sex.toLowerCase() : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
        <div className="p-4">
          <div className="eyebrow">Screened against</div>
          <div className="readout mt-1 text-[17px] font-semibold leading-tight">
            {trial.trial_id}
          </div>
          <div className="mt-1 font-sans text-[12.5px] leading-snug text-ink-mid">
            {trial.title}
          </div>
        </div>
      </div>

      <OverallBanner status={result.overall_status} reason={result.status_reason} />

      <Tallies result={result} />

      {result.heuristic_flags.length > 0 && (
        <HeuristicList flags={result.heuristic_flags} />
      )}
    </div>
  );
}

function Tallies({ result }: { result: ScreeningResult }) {
  const coverage = Math.round(result.rule_coverage * 100);

  return (
    <div className="border border-rule bg-panel">
      <div className="stagger grid grid-cols-3 gap-px bg-rule">
        <Tally label="Pass" value={result.passed_count} tone="safe" />
        <Tally label="Fail" value={result.failed_count} tone="alert" />
        <Tally label="Unknown" value={result.unknown_count} tone="unknown" />
      </div>

      <div className="p-3">
        <div className="flex items-baseline justify-between">
          <span className="eyebrow">Rule coverage</span>
          <span className="readout text-[15px] font-semibold">{coverage}%</span>
        </div>
        {/* How much of the protocol the deterministic engine could verify at
            all — the honest denominator behind the verdict. */}
        <div className="mt-1.5 h-1.5 w-full bg-band" role="img" aria-label={`${coverage}% of criteria machine-verifiable`}>
          <div className="h-full bg-ink" style={{ width: `${coverage}%` }} />
        </div>
        <p className="mt-1.5 font-sans text-[11px] leading-relaxed text-ink-faint">
          criteria the deterministic engine could verify. The rest were referred,
          not guessed.
        </p>
      </div>
    </div>
  );
}

function Tally({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "safe" | "alert" | "unknown";
}) {
  const empty = value === 0;
  const mark =
    tone === "safe"
      ? "bg-safe"
      : tone === "alert"
        ? "bg-alert"
        : "hatch border border-rule-strong";
  const text =
    empty || tone === "unknown"
      ? "text-ink"
      : tone === "safe"
        ? "text-safe"
        : "text-alert";

  return (
    <div className="bg-panel p-3">
      <div className="flex items-center gap-1.5">
        <span className={`inline-block h-2.5 w-2.5 ${empty ? "bg-band" : mark}`} aria-hidden />
        <span className="eyebrow">{label}</span>
      </div>
      <div className={`readout mt-1 text-[24px] font-semibold leading-none ${empty ? "text-ink-faint" : text}`}>
        {value}
      </div>
    </div>
  );
}

/**
 * What the record itself made hard. These are not verdicts — they are the
 * reasons a verdict needed a human, so each kind is marked as its own class of
 * problem rather than as a generic list item.
 */
const FLAG_KIND: Record<string, { label: string; mark: string }> = {
  CONTRADICTORY_DATA: { label: "Contradiction", mark: "bg-alert" },
  BORDERLINE_VALUE: { label: "At the boundary", mark: "stripe-caution" },
  UNSUPPORTED_CRITERION: { label: "Not machine-verifiable", mark: "hatch border border-rule-strong" },
};

function HeuristicList({ flags }: { flags: HeuristicFlag[] }) {
  return (
    <section className="border border-rule bg-panel">
      <h2 className="eyebrow border-b border-rule px-3 py-2">
        Why this needed reading
      </h2>
      <ul>
        {flags.map((flag, index) => {
          const kind = FLAG_KIND[flag.code];
          return (
            <li
              key={`${flag.code}-${index}`}
              className={`flex gap-2.5 p-3 ${index > 0 ? "border-t border-rule" : ""}`}
            >
              <span
                className={`mt-1 h-2.5 w-2.5 shrink-0 ${kind?.mark ?? "bg-ink"}`}
                aria-hidden
              />
              <div className="min-w-0">
                <div className="font-sans text-[12px] font-semibold">
                  {kind?.label ?? flag.code}
                </div>
                <p className="mt-0.5 font-sans text-[12px] leading-relaxed text-ink-mid">
                  {flag.message}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
