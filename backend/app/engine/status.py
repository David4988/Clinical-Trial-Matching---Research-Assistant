"""Overall status derivation.

Deterministic and ordered. The AI layer contributes to this only indirectly:
a disagreement it raises can force REVIEW_REQUIRED, but it can never produce
ELIGIBLE or INELIGIBLE, and it can never clear a FAIL.
"""

from __future__ import annotations

from ..schema.enums import CriterionStatus, OverallStatus, Severity
from ..schema.result import CriterionResult, Disagreement, HeuristicFlag


def derive_overall_status(
    criteria_results: list[CriterionResult],
    heuristic_flags: list[HeuristicFlag],
    disagreements: list[Disagreement],
) -> tuple[OverallStatus, str]:
    """Return the overall status and a one-line explanation of why.

    Precedence, highest first:
      1. any FAIL              -> INELIGIBLE      (dominates everything)
      2. any disagreement      -> REVIEW_REQUIRED
      3. any UNKNOWN           -> REVIEW_REQUIRED
      4. any WARN heuristic    -> REVIEW_REQUIRED
      5. otherwise             -> ELIGIBLE
    """
    failed = [r for r in criteria_results if r.status is CriterionStatus.FAIL]
    if failed:
        ids = ", ".join(r.criterion_id for r in failed)
        return (
            OverallStatus.INELIGIBLE,
            f"{len(failed)} criterion/criteria failed deterministically ({ids}).",
        )

    if not criteria_results:
        return (
            OverallStatus.REVIEW_REQUIRED,
            "The trial defines no criteria, so nothing could be verified.",
        )

    if disagreements:
        ids = ", ".join(d.criterion_id for d in disagreements)
        return (
            OverallStatus.REVIEW_REQUIRED,
            f"AI interpretation conflicts with the rule engine on: {ids}.",
        )

    unknown = [r for r in criteria_results if r.status is CriterionStatus.UNKNOWN]
    if unknown:
        ids = ", ".join(r.criterion_id for r in unknown)
        return (
            OverallStatus.REVIEW_REQUIRED,
            f"{len(unknown)} criterion/criteria could not be evaluated ({ids}).",
        )

    warnings = [f for f in heuristic_flags if f.severity is Severity.WARN]
    if warnings:
        codes = ", ".join(sorted({f.code.value for f in warnings}))
        return (
            OverallStatus.REVIEW_REQUIRED,
            f"Heuristic warnings raised: {codes}.",
        )

    return (
        OverallStatus.ELIGIBLE,
        "All criteria were deterministically verified and passed.",
    )


def count_statuses(results: list[CriterionResult]) -> tuple[int, int, int]:
    """(passed, failed, unknown)"""
    passed = sum(1 for r in results if r.status is CriterionStatus.PASS)
    failed = sum(1 for r in results if r.status is CriterionStatus.FAIL)
    unknown = sum(1 for r in results if r.status is CriterionStatus.UNKNOWN)
    return passed, failed, unknown
