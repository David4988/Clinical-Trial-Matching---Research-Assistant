"""Advisory heuristic layer.

Heuristics describe *the quality of the screening*, not the eligibility of the
patient. A WARN can escalate an otherwise-clean result to REVIEW_REQUIRED, but
it can never clear a deterministic FAIL and never produces PASS.

No ML, no training, no invented probabilities. Every flag here is a plain
observable property of the record.
"""

from __future__ import annotations

from ..schema.clinical import Patient
from ..schema.enums import (
    CriterionStatus,
    HeuristicCode,
    NumericOp,
    Severity,
)
from ..schema.result import CriterionResult, HeuristicFlag
from ..schema.trial import NumericRule, Trial, normalize_term
from ..engine.evaluators import evaluate_numeric
from ..engine.resolver import resolve_numeric_field, units_compatible

# A passing value within this relative distance of a boundary is "borderline".
BORDERLINE_THRESHOLD = 0.05
# Below this fraction of machine-evaluable criteria, the screening as a whole
# is too thin to stand on its own.
MIN_RULE_COVERAGE = 0.6


def collect_flags(
    patient: Patient, trial: Trial, results: list[CriterionResult]
) -> list[HeuristicFlag]:
    flags: list[HeuristicFlag] = []
    flags.extend(_missing_and_unsupported(trial, results))
    flags.extend(_unit_mismatches(patient, trial))
    flags.extend(_borderline_values(patient, trial, results))
    flags.extend(_contradictory_labs(patient))
    flags.extend(_incomplete_record(patient))
    flags.extend(_low_coverage(trial))
    return flags


def _missing_and_unsupported(
    trial: Trial, results: list[CriterionResult]
) -> list[HeuristicFlag]:
    by_id = {c.criterion_id: c for c in trial.criteria}
    unsupported: list[str] = []
    missing: list[str] = []

    for result in results:
        if result.status is not CriterionStatus.UNKNOWN:
            continue
        criterion = by_id.get(result.criterion_id)
        if criterion is not None and not criterion.is_supported:
            unsupported.append(result.criterion_id)
        else:
            missing.append(result.criterion_id)

    flags: list[HeuristicFlag] = []
    if missing:
        flags.append(
            HeuristicFlag(
                code=HeuristicCode.MISSING_FIELD,
                severity=Severity.WARN,
                message=(
                    f"{len(missing)} criterion/criteria could not be evaluated "
                    "because the patient record lacks the required information."
                ),
                criterion_ids=missing,
            )
        )
    if unsupported:
        flags.append(
            HeuristicFlag(
                code=HeuristicCode.UNSUPPORTED_CRITERION,
                severity=Severity.WARN,
                message=(
                    f"{len(unsupported)} criterion/criteria are not expressible in the "
                    "Phase 1 rule vocabulary and were referred to the advisory AI layer."
                ),
                criterion_ids=unsupported,
            )
        )
    return flags


def _unit_mismatches(patient: Patient, trial: Trial) -> list[HeuristicFlag]:
    flags: list[HeuristicFlag] = []
    for criterion in trial.criteria:
        rule = criterion.rule
        if not isinstance(rule, NumericRule) or rule.unit is None:
            continue
        resolved = resolve_numeric_field(patient, rule.field)
        if not resolved.found:
            continue
        if not units_compatible(rule.unit, resolved.unit):
            flags.append(
                HeuristicFlag(
                    code=HeuristicCode.UNIT_MISMATCH,
                    severity=Severity.WARN,
                    message=(
                        f"{resolved.label}: criterion requires {rule.unit} but the record "
                        f"reports {resolved.unit}. No conversion was applied; the "
                        "criterion was left UNKNOWN."
                    ),
                    criterion_ids=[criterion.criterion_id],
                )
            )
    return flags


def _borderline_values(
    patient: Patient, trial: Trial, results: list[CriterionResult]
) -> list[HeuristicFlag]:
    resolved_status = {r.criterion_id: r.status for r in results}
    flags: list[HeuristicFlag] = []

    for criterion in trial.criteria:
        rule = criterion.rule
        if not isinstance(rule, NumericRule):
            continue
        if resolved_status.get(criterion.criterion_id) is CriterionStatus.UNKNOWN:
            continue
        evaluation = evaluate_numeric(rule, patient)
        distance = evaluation.boundary_distance
        if distance is None or distance > BORDERLINE_THRESHOLD:
            continue
        flags.append(
            HeuristicFlag(
                code=HeuristicCode.BORDERLINE_VALUE,
                severity=Severity.INFO,
                message=(
                    f"{criterion.text}: observed {evaluation.observed} sits within "
                    f"{BORDERLINE_THRESHOLD:.0%} of the threshold. Confirm the source value."
                ),
                criterion_ids=[criterion.criterion_id],
            )
        )
    return flags


def _contradictory_labs(patient: Patient) -> list[HeuristicFlag]:
    """The same analyte reported more than once with different values."""
    # Keyed by normalised name so "HbA1c" and "hba1c" collapse, but the
    # patient's own spelling is what gets shown back to the reviewer.
    seen: dict[str, tuple[str, list[float]]] = {}
    for lab in patient.labs:
        display, values = seen.setdefault(normalize_term(lab.name), (lab.name, []))
        values.append(lab.value)

    flags: list[HeuristicFlag] = []
    for name, values in seen.values():
        if len(set(values)) > 1:
            rendered = ", ".join(str(v) for v in values)
            flags.append(
                HeuristicFlag(
                    code=HeuristicCode.CONTRADICTORY_DATA,
                    severity=Severity.WARN,
                    message=(
                        f"{name} appears {len(values)} times with differing values "
                        f"({rendered}). The most recent value was used."
                    ),
                )
            )
    return flags


def _incomplete_record(patient: Patient) -> list[HeuristicFlag]:
    missing = [
        label
        for label, present in (
            ("age", patient.age is not None),
            ("conditions", bool(patient.conditions)),
            ("medications", bool(patient.medications)),
            ("laboratory results", bool(patient.labs)),
        )
        if not present
    ]
    if not missing:
        return []
    return [
        HeuristicFlag(
            code=HeuristicCode.INCOMPLETE_RECORD,
            severity=Severity.INFO,
            message=f"Patient record has no {', '.join(missing)}.",
        )
    ]


def _low_coverage(trial: Trial) -> list[HeuristicFlag]:
    if not trial.criteria:
        return []
    supported = sum(1 for c in trial.criteria if c.is_supported)
    coverage = supported / len(trial.criteria)
    if coverage >= MIN_RULE_COVERAGE:
        return []
    return [
        HeuristicFlag(
            code=HeuristicCode.LOW_RULE_COVERAGE,
            severity=Severity.WARN,
            message=(
                f"Only {supported}/{len(trial.criteria)} criteria "
                f"({coverage:.0%}) were machine-evaluable."
            ),
        )
    ]


__all__ = ["collect_flags", "BORDERLINE_THRESHOLD", "MIN_RULE_COVERAGE", "NumericOp"]
