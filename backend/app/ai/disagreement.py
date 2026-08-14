"""Disagreement detection between the rule engine and the advisory AI layer.

Disagreements are surfaced, never resolved. Neither side is promoted to the
truth; the result is escalated to a human. This is the mechanism that makes
the AI layer safe to extend with a real model in Phase 2.
"""

from __future__ import annotations

from ..schema.enums import AIVerdict, CriterionStatus
from ..schema.result import AIAnalysis, CriterionResult, Disagreement

# A disagreement requires a definite verdict on BOTH sides. If the rule engine
# said UNKNOWN there is nothing to contradict, and an AMBIGUOUS opinion is not
# a claim. Escalating those would drown the real conflicts in noise.
_CONFLICTS: set[tuple[CriterionStatus, AIVerdict]] = {
    (CriterionStatus.PASS, AIVerdict.NOT_SUPPORTED),
    (CriterionStatus.FAIL, AIVerdict.SUPPORTED),
}


def detect_disagreements(
    criteria_results: list[CriterionResult], ai_analysis: AIAnalysis | None
) -> list[Disagreement]:
    if ai_analysis is None or ai_analysis.degraded:
        return []

    opinions = {o.criterion_id: o for o in ai_analysis.opinions}
    disagreements: list[Disagreement] = []

    for result in criteria_results:
        opinion = opinions.get(result.criterion_id)
        if opinion is None:
            continue
        if (result.status, opinion.verdict) not in _CONFLICTS:
            continue
        disagreements.append(
            Disagreement(
                criterion_id=result.criterion_id,
                rule_status=result.status,
                ai_verdict=opinion.verdict,
                description=(
                    f"Rule engine returned {result.status.value} "
                    f"(expected: {result.expected}; observed: {result.observed or 'n/a'}). "
                    f"AI returned {opinion.verdict.value} at confidence "
                    f"{opinion.confidence:.2f}: {opinion.rationale} "
                    "The conflict is reported for human review; neither verdict was applied."
                ),
            )
        )
    return disagreements
