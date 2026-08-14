import type { AIAnalysis, Disagreement } from "../types/canonical";

/**
 * The AI section is deliberately subordinate: hatched top edge, muted type,
 * placed after the ledger, and labelled as advisory in the heading itself.
 * It must never read as the authority on the page.
 */

export function AIPanel({
  analysis,
  disagreements,
}: {
  analysis: AIAnalysis | null;
  disagreements: Disagreement[];
}) {
  if (!analysis) return null;

  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="eyebrow">AI assistance · advisory</h2>
        <span className="text-[11px] text-ink-faint">{analysis.provider}</span>
      </div>

      <div className="border border-rule bg-panel">
        <div className="hatch h-1.5" />

        <div className="p-4">
          <p className="font-sans text-[13px] leading-relaxed text-ink-mid">
            {analysis.summary}
          </p>

          <p className="mt-3 border-l-2 border-rule-strong pl-3 font-sans text-[12px] leading-relaxed text-ink-faint">
            This layer interprets wording, normalises terminology, and flags
            ambiguity. It does not decide eligibility. Where it contradicts the
            rule engine, the contradiction is reported and the screening is held
            for a human.
          </p>

          {analysis.degraded && (
            <p className="mt-3 text-[12px] text-ink-mid">
              The AI layer was unavailable for this screening. Deterministic
              results above are unaffected.
            </p>
          )}

          {disagreements.length > 0 && (
            <div className="mt-4">
              <div className="eyebrow mb-2">
                Unresolved disagreements ({disagreements.length})
              </div>
              <ul className="space-y-2">
                {disagreements.map((d) => (
                  <li
                    key={d.criterion_id}
                    className="border border-alert/30 bg-alert-wash p-3"
                  >
                    <div className="text-[11px] font-medium text-alert">
                      {d.criterion_id} · rule {d.rule_status} vs AI {d.ai_verdict}
                    </div>
                    <p className="mt-1 font-sans text-[12px] leading-relaxed text-ink-mid">
                      {d.description}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
