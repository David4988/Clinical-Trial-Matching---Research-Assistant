"""Per-criterion evaluation: the only module that knows INCLUSION vs EXCLUSION.

PASS always means "the patient satisfies this criterion for enrollment".
Getting this inversion wrong turns "patient has an excluded condition" into a
green tick, so it lives in one explicit table with dedicated tests rather than
being scattered through if-statements.
"""

from __future__ import annotations

from ..schema.clinical import Evidence, Patient
from ..schema.enums import CriterionKind, CriterionStatus, EvidenceSource
from ..schema.result import CriterionResult
from ..schema.trial import Criterion, Trial
from .evaluators import Evaluation, evaluate_rule

#            rule matched -> status, by criterion kind
_INVERSION: dict[tuple[CriterionKind, bool], CriterionStatus] = {
    (CriterionKind.INCLUSION, True): CriterionStatus.PASS,
    (CriterionKind.INCLUSION, False): CriterionStatus.FAIL,
    (CriterionKind.EXCLUSION, True): CriterionStatus.FAIL,
    (CriterionKind.EXCLUSION, False): CriterionStatus.PASS,
}


def apply_inversion(kind: CriterionKind, matched: bool | None) -> CriterionStatus:
    """The truth table. An unresolved rule is UNKNOWN for both kinds."""
    if matched is None:
        return CriterionStatus.UNKNOWN
    return _INVERSION[(kind, matched)]


def evaluate_criterion(criterion: Criterion, patient: Patient) -> CriterionResult:
    if criterion.rule is None:
        return _unsupported_result(criterion)

    evaluation: Evaluation = evaluate_rule(criterion.rule, patient)
    status = apply_inversion(criterion.kind, evaluation.match)

    evidence = list(evaluation.evidence)
    evidence.append(_verdict_evidence(criterion, evaluation, status))

    return CriterionResult(
        criterion_id=criterion.criterion_id,
        kind=criterion.kind,
        text=criterion.text,
        status=status,
        raw_match=evaluation.match,
        expected=criterion.describe_expected(),
        observed=evaluation.observed,
        evidence=evidence,
    )


def _unsupported_result(criterion: Criterion) -> CriterionResult:
    """A criterion with no machine rule. Never guessed — always UNKNOWN.

    This is the one place the mock AI layer is allowed to have an opinion that
    isn't already covered by the deterministic engine.
    """
    return CriterionResult(
        criterion_id=criterion.criterion_id,
        kind=criterion.kind,
        text=criterion.text,
        status=CriterionStatus.UNKNOWN,
        raw_match=None,
        expected="Not machine-evaluable",
        observed=None,
        evidence=[
            Evidence(
                source_type=EvidenceSource.RULE,
                locator=criterion.criterion_id,
                snippet=criterion.text,
                note=(
                    "No deterministic rule covers this criterion in Phase 1. "
                    "Referred to the advisory AI layer and flagged for human review."
                ),
            )
        ],
    )


def _verdict_evidence(
    criterion: Criterion, evaluation: Evaluation, status: CriterionStatus
) -> Evidence:
    if evaluation.match is None:
        note = evaluation.reason or "Required information unavailable."
    else:
        matched = "matched" if evaluation.match else "did not match"
        note = (
            f"Rule {matched}; criterion is {criterion.kind.value.lower()}, "
            f"therefore {status.value}."
        )
    return Evidence(
        source_type=EvidenceSource.RULE,
        locator=criterion.criterion_id,
        snippet=criterion.describe_expected(),
        note=note,
    )


def evaluate_trial(trial: Trial, patient: Patient) -> list[CriterionResult]:
    return [evaluate_criterion(c, patient) for c in trial.criteria]


def rule_coverage(trial: Trial) -> float:
    """Fraction of criteria the deterministic engine can actually verify."""
    if not trial.criteria:
        return 0.0
    supported = sum(1 for c in trial.criteria if c.is_supported)
    return round(supported / len(trial.criteria), 4)
