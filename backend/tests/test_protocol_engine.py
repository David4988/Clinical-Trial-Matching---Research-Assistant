"""M7-M9: the deterministic protocol layer.

Interventions, notifications, the trust gate, transitions and next-dose
decisions — everything that turns a risk level into an action, and the rules
that stop a model from doing so itself.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring import protocol
from app.monitoring.gate import apply_trust_gate, detect_transition
from app.monitoring.interventions import build_interventions
from app.monitoring.next_dose import assess_next_dose
from app.monitoring.notifications import (
    InAppNotificationProvider,
    build_notifications,
)
from app.schema.enums import EvidenceSource, Severity
from app.schema.monitoring import AdverseEvent, TreatmentAssignment
from app.schema.monitoring_enums import (
    AdverseEventSeverity,
    DataQualityCode,
    DataQualityStatus,
    InterventionAction,
    NextDoseDecision,
    NotificationAudience,
    RiskLevel,
    TreatmentStatus,
)
from app.schema.monitoring_result import (
    DataQuality,
    DataQualityFlag,
    EffectiveRisk,
    MeasurementSummary,
    PatientState,
    RiskAssessment,
)
from app.schema.monitoring_enums import MeasurementType, TrendDirection

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _state(quality_status=DataQualityStatus.OK, adverse_events=None, fresh=True):
    flags = []
    if quality_status is DataQualityStatus.UNTRUSTWORTHY:
        flags = [
            DataQualityFlag(
                code=DataQualityCode.STALE_OBSERVATION,
                severity=Severity.WARN,
                message="SPO2 has no reading within the last 90 minutes.",
            )
        ]
    return PatientState(
        patient_id="P-1042",
        trial_id="CT-001",
        as_of=NOW,
        measurements=[
            MeasurementSummary(
                measurement_type=m,
                unit="x",
                baseline=70.0,
                current=72.0,
                latest_at=NOW,
                trend=TrendDirection.STABLE,
                sample_count=6,
                is_stale=not fresh,
            )
            for m in protocol.REQUIRED_MEASUREMENTS
        ],
        active_adverse_events=adverse_events or [],
        data_quality=DataQuality(status=quality_status, flags=flags),
        observation_count=18,
    )


def _risk(level=RiskLevel.GREEN, score=0.1, degraded=False, factors=None):
    return RiskAssessment(
        assessment_id="RA-1",
        patient_id="P-1042",
        trial_id="CT-001",
        assessed_at=NOW,
        level=level,
        score=score,
        confidence=0.9,
        prediction_horizon_hours=protocol.PREDICTION_HORIZON_HOURS,
        contributing_factors=factors or [],
        provider="mock-risk-v1",
        model_version="0.1.0",
        degraded=degraded,
    )


def _effective(level, provider_level=None, gated=False):
    return EffectiveRisk(
        level=level,
        provider_level=provider_level or level,
        gated=gated,
        reason="test",
    )


def _treatment(status=TreatmentStatus.ACTIVE):
    return TreatmentAssignment(
        treatment_id="TX-1",
        patient_id="P-1042",
        trial_id="CT-001",
        screening_result_id="SR-1",
        drug_name="Compound X",
        status=status,
        registered_at=NOW - timedelta(days=1),
    )


def _severe_event():
    return AdverseEvent(
        event_id="AE-1",
        patient_id="P-1042",
        trial_id="CT-001",
        term="Anaphylaxis",
        severity=AdverseEventSeverity.SEVERE,
        onset_at=NOW,
    )


# =========================================================================
# The trust gate
# =========================================================================


def test_untrustworthy_data_forces_unknown_over_a_green_model_verdict():
    """The central Phase 2 safety property."""
    state = _state(DataQualityStatus.UNTRUSTWORTHY)

    effective = apply_trust_gate(state, _risk(RiskLevel.GREEN, 0.05))

    assert effective.level is RiskLevel.UNKNOWN
    assert effective.provider_level is RiskLevel.GREEN
    assert effective.gated is True


def test_the_gate_retains_what_the_model_said():
    """Overridden, not erased — a reviewer must see both."""
    effective = apply_trust_gate(
        _state(DataQualityStatus.UNTRUSTWORTHY), _risk(RiskLevel.RED, 0.9)
    )

    assert effective.provider_level is RiskLevel.RED
    assert "no risk verdict was applied" in effective.reason
    # The specific data-quality problem is named, not just asserted.
    assert "90 minutes" in effective.reason


def test_trustworthy_data_passes_the_model_verdict_through():
    effective = apply_trust_gate(_state(DataQualityStatus.OK), _risk(RiskLevel.AMBER, 0.5))

    assert effective.level is RiskLevel.AMBER
    assert effective.gated is False


def test_degraded_data_is_still_actionable():
    """DEGRADED means 'say so', not 'stop'."""
    effective = apply_trust_gate(
        _state(DataQualityStatus.DEGRADED), _risk(RiskLevel.AMBER, 0.5)
    )

    assert effective.level is RiskLevel.AMBER
    assert effective.gated is False


def test_a_degraded_provider_cannot_produce_an_actionable_level():
    effective = apply_trust_gate(_state(), _risk(RiskLevel.GREEN, 0.0, degraded=True))

    assert effective.level is RiskLevel.UNKNOWN
    assert effective.gated is True


# =========================================================================
# Transitions
# =========================================================================


def test_first_assessment_is_a_transition_from_nothing():
    transition = detect_transition(None, _effective(RiskLevel.GREEN), "P-1", "CT-1", NOW)

    assert transition is not None
    assert transition.from_level is None
    assert transition.to_level is RiskLevel.GREEN


def test_unchanged_level_is_not_a_transition():
    assert (
        detect_transition(RiskLevel.AMBER, _effective(RiskLevel.AMBER), "P-1", "CT-1", NOW)
        is None
    )


def test_escalation_and_de_escalation_are_described():
    up = detect_transition(RiskLevel.GREEN, _effective(RiskLevel.RED), "P-1", "CT-1", NOW)
    down = detect_transition(RiskLevel.RED, _effective(RiskLevel.GREEN), "P-1", "CT-1", NOW)

    assert "Escalated" in up.trigger
    assert "De-escalated" in down.trigger


def test_unknown_ranks_above_amber_as_an_escalation():
    """Not knowing is more concerning than a known mild excursion."""
    transition = detect_transition(
        RiskLevel.AMBER, _effective(RiskLevel.UNKNOWN), "P-1", "CT-1", NOW
    )

    assert "Escalated" in transition.trigger


# =========================================================================
# Interventions
# =========================================================================


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (RiskLevel.GREEN, {InterventionAction.ROUTINE_MONITORING}),
        (
            RiskLevel.AMBER,
            {
                InterventionAction.INCREASE_MONITORING,
                InterventionAction.CLINICAL_REVIEW,
                InterventionAction.NOTIFY_CLINICIAN,
            },
        ),
        (
            RiskLevel.RED,
            {
                InterventionAction.URGENT_ESCALATION,
                InterventionAction.NOTIFY_CLINICIAN,
                InterventionAction.INCREASE_MONITORING,
            },
        ),
        (
            RiskLevel.UNKNOWN,
            {
                InterventionAction.REQUEST_REPEAT_OBSERVATION,
                InterventionAction.CLINICAL_REVIEW,
                InterventionAction.NOTIFY_CLINICIAN,
            },
        ),
    ],
)
def test_each_level_produces_its_protocol_actions(level, expected):
    interventions = build_interventions(_state(), _effective(level), _risk(level), NOW)

    assert {i.action for i in interventions} == expected


def test_unknown_does_not_fall_back_to_routine_monitoring():
    """Missing data must produce more attention, not less."""
    interventions = build_interventions(
        _state(DataQualityStatus.UNTRUSTWORTHY),
        _effective(RiskLevel.UNKNOWN, RiskLevel.GREEN, gated=True),
        _risk(RiskLevel.GREEN),
        NOW,
    )
    actions = {i.action for i in interventions}

    assert InterventionAction.ROUTINE_MONITORING not in actions
    assert InterventionAction.REQUEST_REPEAT_OBSERVATION in actions


def test_monitoring_intensity_increases_with_risk():
    def interval(level):
        interventions = build_interventions(
            _state(), _effective(level), _risk(level), NOW
        )
        return next(
            i.monitoring_interval_minutes
            for i in interventions
            if i.monitoring_interval_minutes is not None
        )

    assert interval(RiskLevel.GREEN) > interval(RiskLevel.AMBER) > interval(RiskLevel.RED)


def test_every_intervention_cites_a_protocol_rule():
    for level in RiskLevel:
        for intervention in build_interventions(
            _state(), _effective(level), _risk(level), NOW
        ):
            assert intervention.protocol_rule_id == protocol.RULE_IDS[level]
            assert intervention.rationale


def test_green_interventions_are_informational():
    interventions = build_interventions(
        _state(), _effective(RiskLevel.GREEN), _risk(RiskLevel.GREEN), NOW
    )
    assert all(i.severity is Severity.INFO for i in interventions)


def test_red_interventions_carry_warning_severity():
    interventions = build_interventions(
        _state(), _effective(RiskLevel.RED), _risk(RiskLevel.RED, 0.9), NOW
    )
    assert all(i.severity is Severity.WARN for i in interventions)


def test_intervention_evidence_leads_with_the_protocol_rule():
    """The protocol is the authority; the model is a downstream citation."""
    interventions = build_interventions(
        _state(), _effective(RiskLevel.AMBER), _risk(RiskLevel.AMBER, 0.5), NOW
    )
    first = interventions[0].evidence[0]

    assert first.source_type is EvidenceSource.RULE
    assert first.locator == protocol.RULE_IDS[RiskLevel.AMBER]


def test_gated_interventions_record_the_override_in_evidence():
    interventions = build_interventions(
        _state(DataQualityStatus.UNTRUSTWORTHY),
        _effective(RiskLevel.UNKNOWN, RiskLevel.GREEN, gated=True),
        _risk(RiskLevel.GREEN),
        NOW,
    )
    locators = [e.locator for e in interventions[0].evidence]

    assert "DATA-QUALITY-GATE" in locators


# =========================================================================
# Notifications
# =========================================================================


def test_green_generates_no_notification():
    interventions = build_interventions(
        _state(), _effective(RiskLevel.GREEN), _risk(RiskLevel.GREEN), NOW
    )
    assert build_notifications(_state(), _effective(RiskLevel.GREEN), interventions, NOW) == []


@pytest.mark.parametrize("level", [RiskLevel.AMBER, RiskLevel.RED, RiskLevel.UNKNOWN])
def test_escalating_levels_notify_a_clinician(level):
    state = _state()
    effective = _effective(level)
    interventions = build_interventions(state, effective, _risk(level), NOW)

    notifications = build_notifications(state, effective, interventions, NOW)

    assert notifications
    assert all(n.audience is NotificationAudience.CLINICIAN for n in notifications)


def test_the_algorithm_never_generates_a_patient_message():
    """Patient contact stays behind a human approval, per docs/PHASES.md."""
    for level in RiskLevel:
        state = _state()
        effective = _effective(level)
        notifications = build_notifications(
            state, effective, build_interventions(state, effective, _risk(level), NOW), NOW
        )
        assert all(n.audience is not NotificationAudience.PATIENT for n in notifications)


def test_generation_does_not_deliver():
    state, effective = _state(), _effective(RiskLevel.RED)
    notifications = build_notifications(
        state, effective, build_interventions(state, effective, _risk(RiskLevel.RED), NOW), NOW
    )

    assert all(n.is_delivered is False for n in notifications)
    assert all(n.delivery_provider is None for n in notifications)


def test_delivery_is_a_separate_step():
    state, effective = _state(), _effective(RiskLevel.RED)
    notification = build_notifications(
        state, effective, build_interventions(state, effective, _risk(RiskLevel.RED), NOW), NOW
    )[0]

    delivered = InAppNotificationProvider().deliver(notification, NOW)

    assert delivered.is_delivered is True
    assert delivered.delivery_provider == "in-app-mock"
    # The original object is untouched.
    assert notification.is_delivered is False


def test_notification_body_explains_a_gated_verdict():
    state = _state(DataQualityStatus.UNTRUSTWORTHY)
    effective = _effective(RiskLevel.UNKNOWN, RiskLevel.GREEN, gated=True)
    notifications = build_notifications(
        state, effective, build_interventions(state, effective, _risk(RiskLevel.GREEN), NOW), NOW
    )

    assert "GREEN" in notifications[0].body
    assert "decision support only" in notifications[0].body.lower()


# =========================================================================
# Next dose
# =========================================================================


def test_green_and_clean_proceeds():
    assessment = assess_next_dose(_state(), _effective(RiskLevel.GREEN), _treatment(), NOW)

    assert assessment.decision is NextDoseDecision.PROCEED
    assert assessment.blocking_criteria == []
    assert assessment.proposed_dose_number == 1


def test_amber_requires_review():
    assessment = assess_next_dose(_state(), _effective(RiskLevel.AMBER), _treatment(), NOW)

    assert assessment.decision is NextDoseDecision.REVIEW_REQUIRED
    assert "ND-01" in assessment.blocking_criteria


def test_red_holds_the_dose():
    assessment = assess_next_dose(_state(), _effective(RiskLevel.RED), _treatment(), NOW)

    assert assessment.decision is NextDoseDecision.HOLD
    assert "ND-01" in assessment.blocking_criteria


def test_unknown_risk_requires_review_and_is_never_proceed():
    assessment = assess_next_dose(
        _state(DataQualityStatus.UNTRUSTWORTHY),
        _effective(RiskLevel.UNKNOWN, RiskLevel.GREEN, gated=True),
        _treatment(),
        NOW,
    )

    assert assessment.decision is NextDoseDecision.REVIEW_REQUIRED
    risk_criterion = next(c for c in assessment.criteria if c.criterion_id == "ND-01")
    assert risk_criterion.satisfied is None


def test_an_unevaluable_criterion_is_never_counted_as_passed():
    """The Phase 1 UNKNOWN philosophy, applied to dosing."""
    assessment = assess_next_dose(_state(), _effective(RiskLevel.GREEN), None, NOW)

    treatment_criterion = next(c for c in assessment.criteria if c.criterion_id == "ND-05")
    assert treatment_criterion.satisfied is None
    assert assessment.decision is NextDoseDecision.REVIEW_REQUIRED


def test_severe_adverse_event_holds_the_dose_even_at_green():
    assessment = assess_next_dose(
        _state(adverse_events=[_severe_event()]),
        _effective(RiskLevel.GREEN),
        _treatment(),
        NOW,
    )

    assert assessment.decision is NextDoseDecision.HOLD
    assert "ND-03" in assessment.blocking_criteria


def test_a_held_treatment_blocks_the_next_dose():
    assessment = assess_next_dose(
        _state(), _effective(RiskLevel.GREEN), _treatment(TreatmentStatus.ON_HOLD), NOW
    )

    assert assessment.decision is NextDoseDecision.HOLD
    assert "ND-05" in assessment.blocking_criteria


def test_stale_observations_block_proceed():
    assessment = assess_next_dose(
        _state(fresh=False), _effective(RiskLevel.GREEN), _treatment(), NOW
    )

    assert assessment.decision is not NextDoseDecision.PROCEED
    assert "ND-04" in assessment.blocking_criteria


def test_every_criterion_is_reported_with_its_reasoning():
    assessment = assess_next_dose(_state(), _effective(RiskLevel.RED), _treatment(), NOW)

    assert len(assessment.criteria) == 5
    assert all(c.description and c.detail for c in assessment.criteria)
    assert assessment.reasons


def test_next_dose_is_always_marked_decision_support_only():
    for level in RiskLevel:
        assessment = assess_next_dose(_state(), _effective(level), _treatment(), NOW)
        assert assessment.decision_support_only is True
