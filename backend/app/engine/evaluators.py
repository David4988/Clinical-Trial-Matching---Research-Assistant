"""Rule evaluators.

Each evaluator answers one question: *does this rule match this patient?*
It returns True, False, or None (cannot tell). It never decides PASS/FAIL —
that inversion happens in eligibility.py, which is the only module that knows
about INCLUSION vs EXCLUSION.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from ..schema.clinical import Evidence, Patient
from ..schema.enums import EvidenceSource, NumericOp
from ..schema.trial import NumericRule, PresenceRule, Rule
from .resolver import (
    resolve_numeric_field,
    resolve_presence,
    units_compatible,
)


@dataclass
class Evaluation:
    """Outcome of applying one rule to one patient."""

    match: bool | None
    observed: str | None = None
    evidence: list[Evidence] = dc_field(default_factory=list)
    reason: str | None = None
    unit_mismatch: bool = False
    # Distance from the nearest boundary, as a fraction of the rule's scale.
    # Populated for resolved numeric rules; used by the borderline heuristic.
    boundary_distance: float | None = None


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def evaluate_numeric(rule: NumericRule, patient: Patient) -> Evaluation:
    resolved = resolve_numeric_field(patient, rule.field)

    if not resolved.found or resolved.value is None:
        return Evaluation(match=None, reason=resolved.reason)

    observed = f"{_format_number(resolved.value)} {resolved.unit or ''}".strip()

    if not units_compatible(rule.unit, resolved.unit):
        return Evaluation(
            match=None,
            observed=observed,
            evidence=resolved.evidence,
            unit_mismatch=True,
            reason=(
                f"Unit mismatch: criterion requires {rule.unit}, "
                f"record reports {resolved.unit}. No conversion applied."
            ),
        )

    value = resolved.value
    low, high = rule.low, rule.high

    if rule.op is NumericOp.GTE:
        match = value >= low
    elif rule.op is NumericOp.GT:
        match = value > low
    elif rule.op is NumericOp.LTE:
        match = value <= low
    elif rule.op is NumericOp.LT:
        match = value < low
    elif rule.op is NumericOp.EQ:
        match = value == low
    else:  # BETWEEN — inclusive on both ends
        match = low <= value <= high

    return Evaluation(
        match=match,
        observed=observed,
        evidence=resolved.evidence,
        boundary_distance=_boundary_distance(value, rule),
    )


def _boundary_distance(value: float, rule: NumericRule) -> float | None:
    """Relative distance to the nearest boundary, or None if not meaningful.

    Scaled by the rule's own magnitude so that "close to 45" and "close to 10"
    are comparable. Returned for both passing and failing values.
    """
    bounds = [b for b in (rule.low, rule.high) if b is not None]
    if not bounds:
        return None
    nearest = min(bounds, key=lambda b: abs(value - b))
    scale = max(abs(nearest), 1.0)
    return abs(value - nearest) / scale


def evaluate_presence(rule: PresenceRule, patient: Patient) -> Evaluation:
    resolved = resolve_presence(patient, rule.domain, rule.all_terms())
    return Evaluation(
        match=resolved.matched,
        observed=resolved.observed,
        evidence=resolved.evidence,
        reason=resolved.reason,
    )


def evaluate_rule(rule: Rule, patient: Patient) -> Evaluation:
    if isinstance(rule, NumericRule):
        return evaluate_numeric(rule, patient)
    if isinstance(rule, PresenceRule):
        return evaluate_presence(rule, patient)
    # Defensive: a new rule type added to the schema without an evaluator must
    # degrade to UNKNOWN, never to a silent PASS.
    return Evaluation(
        match=None,
        reason=f"No evaluator registered for rule type '{type(rule).__name__}'",
        evidence=[
            Evidence(
                source_type=EvidenceSource.RULE,
                note="Unhandled rule type; treated as not evaluable.",
            )
        ],
    )
