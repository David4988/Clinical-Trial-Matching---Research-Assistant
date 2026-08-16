"""Next-dose readiness — decision support, never administration.

Nothing in this system gives a dose. This module answers one question for a
human: *does the protocol consider this patient ready for the next dose?* and
shows every check behind the answer.

Two Phase 1 habits carry straight over:

  * A criterion that cannot be evaluated is `satisfied = None`, never silently
    counted as passed. An unevaluable safety check blocks PROCEED.
  * The decision is derived by ordered, deterministic precedence, exactly like
    `engine/status.py` derives an overall screening status.

Precedence, highest first:
    1. any hard blocker      -> HOLD
    2. any unevaluable check -> REVIEW_REQUIRED
    3. any failed check      -> REVIEW_REQUIRED
    4. otherwise             -> PROCEED
"""

from __future__ import annotations

from datetime import datetime

from . import ids, protocol
from ..schema.monitoring import TreatmentAssignment
from ..schema.monitoring_enums import (
    AdverseEventSeverity,
    NextDoseDecision,
    RiskLevel,
    TreatmentStatus,
)
from ..schema.monitoring_result import (
    EffectiveRisk,
    NextDoseAssessment,
    NextDoseCriterion,
    PatientState,
)

#: Criteria whose failure stops the dose outright rather than escalating it.
#:
#: ND-01 (risk level) is conditional: the demo protocol holds the dose at RED,
#: but AMBER escalates to clinical review rather than stopping — which is the
#: difference between "a clinician must look at this" and "do not give it".
_HARD_BLOCKERS = {"ND-03", "ND-05"}
_RISK_CRITERION = "ND-01"


def assess_next_dose(
    state: PatientState,
    effective_risk: EffectiveRisk,
    treatment: TreatmentAssignment | None,
    now: datetime,
) -> NextDoseAssessment:
    criteria = [
        _risk_criterion(effective_risk),
        _data_quality_criterion(state),
        _adverse_event_criterion(state),
        _observation_criterion(state),
        _treatment_criterion(treatment),
    ]

    decision, reasons, blocking = _derive(criteria, effective_risk, state)

    return NextDoseAssessment(
        assessment_id=ids.new_id(ids.NEXT_DOSE),
        patient_id=state.patient_id,
        trial_id=state.trial_id,
        treatment_id=treatment.treatment_id if treatment else "",
        assessed_at=now,
        decision=decision,
        proposed_dose_number=treatment.next_dose_number if treatment else None,
        criteria=criteria,
        reasons=reasons,
        blocking_criteria=blocking,
        risk_level=effective_risk.level,
        data_quality_status=state.data_quality.status,
        decision_support_only=True,
    )


# -- criteria --------------------------------------------------------------


def _risk_criterion(effective_risk: EffectiveRisk) -> NextDoseCriterion:
    level = effective_risk.level
    if level is RiskLevel.UNKNOWN:
        satisfied = None
        detail = (
            "Risk could not be established, so the protocol cannot confirm the "
            "patient is ready. " + effective_risk.reason
        ).strip()
    else:
        satisfied = level is RiskLevel.GREEN
        detail = f"Effective risk level is {level.value}."
        if effective_risk.gated:
            detail += (
                f" (Risk model reported {effective_risk.provider_level.value}; "
                "the data-quality gate applied.)"
            )

    return NextDoseCriterion(
        criterion_id="ND-01",
        description=f"Risk level is {RiskLevel.GREEN.value} under {protocol.PROTOCOL_ID}",
        satisfied=satisfied,
        detail=detail,
    )


def _data_quality_criterion(state: PatientState) -> NextDoseCriterion:
    quality = state.data_quality
    messages = "; ".join(f.message for f in quality.flags)
    return NextDoseCriterion(
        criterion_id="ND-02",
        description="Observation record is trustworthy",
        satisfied=quality.is_trustworthy,
        detail=f"Data quality is {quality.status.value}."
        + (f" {messages}" if messages else ""),
    )


def _adverse_event_criterion(state: PatientState) -> NextDoseCriterion:
    severe = [
        e
        for e in state.active_adverse_events
        if e.severity is AdverseEventSeverity.SEVERE
    ]
    if severe:
        detail = "Active severe adverse event(s): " + ", ".join(e.term for e in severe)
    elif state.active_adverse_events:
        detail = "Active non-severe adverse event(s): " + ", ".join(
            f"{e.term} ({e.severity.value})" for e in state.active_adverse_events
        )
    else:
        detail = "No active adverse events recorded."

    return NextDoseCriterion(
        criterion_id="ND-03",
        description="No active severe adverse event",
        satisfied=not severe,
        detail=detail,
    )


def _observation_criterion(state: PatientState) -> NextDoseCriterion:
    required = protocol.REQUIRED_MEASUREMENTS
    present = {
        s.measurement_type
        for s in state.measurements
        if s.current is not None and not s.is_stale
    }
    missing = [m for m in required if m not in present]

    return NextDoseCriterion(
        criterion_id="ND-04",
        description="Required observations are present and current",
        satisfied=not missing,
        detail=(
            "Missing or stale: " + ", ".join(m.value for m in missing)
            if missing
            else "All protocol-required observations are current."
        ),
    )


def _treatment_criterion(
    treatment: TreatmentAssignment | None,
) -> NextDoseCriterion:
    if treatment is None:
        return NextDoseCriterion(
            criterion_id="ND-05",
            description="An active treatment is registered",
            satisfied=None,
            detail="No treatment is registered for this patient.",
        )
    return NextDoseCriterion(
        criterion_id="ND-05",
        description="An active treatment is registered",
        satisfied=treatment.status is TreatmentStatus.ACTIVE,
        detail=f"Treatment {treatment.treatment_id} is {treatment.status.value}.",
    )


# -- derivation ------------------------------------------------------------


def _derive(
    criteria: list[NextDoseCriterion],
    effective_risk: EffectiveRisk,
    state: PatientState,
) -> tuple[NextDoseDecision, list[str], list[str]]:
    failed = [c for c in criteria if c.satisfied is False]
    unevaluable = [c for c in criteria if c.satisfied is None]

    # RED holds the dose; AMBER escalates it to review.
    hard_ids = set(_HARD_BLOCKERS)
    if effective_risk.level is RiskLevel.RED:
        hard_ids.add(_RISK_CRITERION)

    hard_failures = [c for c in failed if c.criterion_id in hard_ids]
    if hard_failures:
        return (
            NextDoseDecision.HOLD,
            [f"{c.criterion_id}: {c.detail}" for c in hard_failures],
            [c.criterion_id for c in hard_failures],
        )

    if unevaluable:
        return (
            NextDoseDecision.REVIEW_REQUIRED,
            [
                f"{c.criterion_id} could not be evaluated: {c.detail}"
                for c in unevaluable
            ]
            + [
                "An unevaluable safety check is never treated as satisfied.",
            ],
            [c.criterion_id for c in unevaluable],
        )

    if failed:
        return (
            NextDoseDecision.REVIEW_REQUIRED,
            [f"{c.criterion_id}: {c.detail}" for c in failed],
            [c.criterion_id for c in failed],
        )

    return (
        NextDoseDecision.PROCEED,
        [
            f"All {len(criteria)} protocol criteria are satisfied at "
            f"{effective_risk.level.value}.",
            f"Data quality is {state.data_quality.status.value}.",
        ],
        [],
    )
