import type {
  AICriterionOpinion,
  CriterionResult,
  Disagreement,
  NumericRule,
  ScreeningResult,
} from "../types/canonical";
import { RangeBar, observedNumber } from "./RangeBar";
import { VerdictRail, VerdictToken } from "./Verdict";

/**
 * The criterion ledger: one row per criterion, each expandable into its full
 * provenance chain. This is the screen the whole product exists to produce, so
 * everything else on the page stays quieter than it.
 */

export function CriterionLedger({ result }: { result: ScreeningResult }) {
  const criteriaById = new Map(result.trial.criteria.map((c) => [c.criterion_id, c]));
  const opinionsById = new Map(
    (result.ai_analysis?.opinions ?? []).map((o) => [o.criterion_id, o]),
  );
  const disagreementsById = new Map(
    result.disagreements.map((d) => [d.criterion_id, d]),
  );

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="eyebrow">Criterion ledger</h2>
        <span className="text-[11px] text-ink-faint">
          {result.criteria_results.length} criteria · deterministic engine
        </span>
      </div>

      <div className="border border-rule bg-panel">
        {result.criteria_results.map((row, index) => (
          <LedgerRow
            key={row.criterion_id}
            row={row}
            rule={(criteriaById.get(row.criterion_id)?.rule ?? null) as NumericRule | null}
            opinion={opinionsById.get(row.criterion_id)}
            disagreement={disagreementsById.get(row.criterion_id)}
            isLast={index === result.criteria_results.length - 1}
          />
        ))}
      </div>
    </section>
  );
}

function LedgerRow({
  row,
  rule,
  opinion,
  disagreement,
  isLast,
}: {
  row: CriterionResult;
  rule: NumericRule | null;
  opinion?: AICriterionOpinion;
  disagreement?: Disagreement;
  isLast: boolean;
}) {
  const isNumeric = rule?.type === "numeric";

  return (
    <div className={`flex gap-4 ${isLast ? "" : "border-b border-rule"}`}>
      <VerdictRail status={row.status} />

      <div className="min-w-0 flex-1 py-4 pr-4">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-medium text-ink-faint">
                {row.criterion_id}
              </span>
              <span className="text-[10px] tracking-[0.1em] text-ink-faint">
                {row.kind}
              </span>
            </div>
            <p className="mt-1 font-sans text-[15px] leading-snug text-ink">
              {row.text}
            </p>
          </div>
          <VerdictToken status={row.status} />
        </div>

        {/* Expected vs observed */}
        <div className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
          <Field label="Required" value={row.expected} />
          <Field
            label="Observed"
            value={row.observed ?? "Not available"}
            muted={!row.observed}
          />
        </div>

        {isNumeric && rule && (
          <div className="mt-3 max-w-md">
            <RangeBar
              rule={rule}
              observedValue={observedNumber(row.observed)}
              status={row.status}
            />
          </div>
        )}

        {disagreement && <DisagreementNotice disagreement={disagreement} />}

        <EvidenceTrail row={row} opinion={opinion} />
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  muted,
}: {
  label: string;
  value: string;
  muted?: boolean;
}) {
  return (
    <div className="min-w-0">
      <div className="eyebrow mb-0.5">{label}</div>
      <div
        className={`break-words text-[13px] ${muted ? "text-ink-faint" : "text-ink"}`}
      >
        {value}
      </div>
    </div>
  );
}

function DisagreementNotice({ disagreement }: { disagreement: Disagreement }) {
  return (
    <div className="mt-3 border border-alert/30 bg-alert-wash p-3">
      <div className="text-[10px] font-semibold tracking-[0.12em] text-alert">
        RULE / AI DISAGREEMENT
      </div>
      <p className="mt-1 font-sans text-[13px] leading-relaxed text-ink">
        The rule engine returned{" "}
        <strong className="font-mono">{disagreement.rule_status}</strong> and the
        AI layer returned{" "}
        <strong className="font-mono">{disagreement.ai_verdict}</strong>. The
        rule verdict stands; this screening is held for human review.
      </p>
    </div>
  );
}

function EvidenceTrail({
  row,
  opinion,
}: {
  row: CriterionResult;
  opinion?: AICriterionOpinion;
}) {
  return (
    <details className="mt-3 group">
      <summary className="inline-flex items-center gap-1.5 text-[11px] text-ink-mid hover:text-ink">
        <span className="transition-transform group-open:rotate-90">▸</span>
        Evidence ({row.evidence.length})
      </summary>

      <ol className="mt-2 space-y-2 border-l border-rule pl-3">
        {row.evidence.map((item, index) => (
          <li key={index} className="text-[12px] leading-relaxed">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                {item.source_type}
              </span>
              {item.locator && (
                <span className="text-[11px] text-ink-mid">{item.locator}</span>
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

        {opinion && (
          <li className="text-[12px] leading-relaxed">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-[10px] tracking-[0.08em] text-ink-faint">
                AI · ADVISORY
              </span>
              <span className="text-[11px] text-ink-mid">
                {opinion.verdict} · confidence {opinion.confidence.toFixed(2)}
              </span>
            </div>
            <div className="mt-0.5 font-sans text-ink-mid">
              {opinion.rationale}
            </div>
          </li>
        )}
      </ol>
    </details>
  );
}
