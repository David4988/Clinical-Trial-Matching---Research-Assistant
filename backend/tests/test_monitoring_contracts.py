"""Phase 2 contract tests (M0).

No logic exists yet — these pin the *shape* of the canonical monitoring models,
and in particular the two structural boundaries Phase 2 depends on:

  1. A risk provider cannot express a clinical action.
  2. Patient state cannot depend on risk.

Both are asserted against the model fields themselves, so they fail if someone
later adds a convenient field rather than only when behaviour drifts. This is
the direct analogue of Phase 1's `test_ai_never_changes_a_rule_verdict`.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schema.clinical import Evidence
from app.schema.enums import EvidenceSource, OverallStatus, Severity
from app.schema.monitoring import (
    AdverseEvent,
    DoseAdministration,
    EligibilityOverride,
    Observation,
    TreatmentAssignment,
)
from app.schema.monitoring_enums import (
    AdverseEventSeverity,
    DataQualityCode,
    DataQualityStatus,
    InterventionAction,
    MeasurementType,
    MonitoringEventType,
    NextDoseDecision,
    NotificationAudience,
    NotificationChannel,
    ObservationSource,
    RiskLevel,
    TreatmentStatus,
    TrendDirection,
)
from app.schema.monitoring_result import (
    ContributingFactor,
    DataQuality,
    DataQualityFlag,
    EffectiveRisk,
    Intervention,
    MeasurementSummary,
    MonitoringEvent,
    NextDoseAssessment,
    NextDoseCriterion,
    Notification,
    PatientState,
    RiskAssessment,
    RiskTransition,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _observation(**overrides) -> Observation:
    fields = {
        "observation_id": "OBS-1",
        "patient_id": "P-1042",
        "trial_id": "CT-001",
        "recorded_at": NOW,
        "source": ObservationSource.BEDSIDE_MONITOR,
        "measurement_type": MeasurementType.HEART_RATE,
        "value": 72.0,
        "unit": "bpm",
    }
    fields.update(overrides)
    return Observation(**fields)


def _risk(**overrides) -> RiskAssessment:
    fields = {
        "assessment_id": "RA-1",
        "patient_id": "P-1042",
        "trial_id": "CT-001",
        "assessed_at": NOW,
        "level": RiskLevel.GREEN,
        "score": 0.12,
        "confidence": 0.8,
        "prediction_horizon_hours": 24,
        "provider": "mock-risk-v1",
        "model_version": "0.1.0",
    }
    fields.update(overrides)
    return RiskAssessment(**fields)


# -- structural boundaries -------------------------------------------------

# Anything that would let a provider express "do this to the patient".
_ACTION_FIELD_MARKERS = (
    "action",
    "intervention",
    "next_dose",
    "dose_decision",
    "recommendation",
    "order",
    "prescri",
    "treatment_change",
    "escalat",
)


def test_risk_assessment_cannot_express_a_clinical_action():
    """The Phase 2 equivalent of the Phase 1 AI boundary.

    A risk provider returns risk information. If this test fails, someone has
    given the model a way to order clinical care.
    """
    for field_name in RiskAssessment.model_fields:
        lowered = field_name.lower()
        for marker in _ACTION_FIELD_MARKERS:
            assert marker not in lowered, (
                f"RiskAssessment.{field_name} looks like a clinical action. "
                "Risk providers must not be able to express actions; the "
                "deterministic protocol layer owns those."
            )


def test_patient_state_does_not_carry_risk():
    """Risk is computed FROM state, so state must not depend on it."""
    for field_name in PatientState.model_fields:
        assert "risk" not in field_name.lower(), (
            f"PatientState.{field_name} introduces a risk dependency; state is "
            "an input to the risk layer, not an output of it."
        )


def test_intervention_records_the_protocol_rule_that_fired():
    """Every action must trace to a written rule, not to a model's opinion."""
    assert "protocol_rule_id" in Intervention.model_fields


def test_next_dose_assessment_is_marked_decision_support_only():
    assessment = NextDoseAssessment(
        assessment_id="ND-1",
        patient_id="P-1042",
        trial_id="CT-001",
        treatment_id="TX-1",
        assessed_at=NOW,
        decision=NextDoseDecision.PROCEED,
    )
    assert assessment.decision_support_only is True


# -- immutability ----------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (_observation(), "value", 99.0),
        (
            EligibilityOverride(
                approved_by="Dr. Chen",
                reason="EXC-01 reviewed",
                approved_at=NOW,
                screening_status=OverallStatus.REVIEW_REQUIRED,
            ),
            "approved_by",
            "someone else",
        ),
        (
            MonitoringEvent(
                event_id="EV-1",
                patient_id="P-1042",
                trial_id="CT-001",
                occurred_at=NOW,
                event_type=MonitoringEventType.RISK_ASSESSED,
                summary="Risk assessed",
            ),
            "summary",
            "rewritten",
        ),
    ],
)
def test_historical_facts_are_frozen(model, field, value):
    """Observations, overrides and timeline entries are the audit trail."""
    with pytest.raises(ValidationError):
        setattr(model, field, value)


# -- validation ------------------------------------------------------------


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_risk_score_must_be_a_fraction(score):
    with pytest.raises(ValidationError):
        _risk(score=score)


@pytest.mark.parametrize("confidence", [-0.5, 1.5])
def test_risk_confidence_must_be_a_fraction(confidence):
    with pytest.raises(ValidationError):
        _risk(confidence=confidence)


def test_contributing_factor_weight_is_bounded():
    with pytest.raises(ValidationError):
        ContributingFactor(factor="hr", detail="rising", weight=1.4)


def test_prediction_horizon_cannot_be_negative():
    with pytest.raises(ValidationError):
        _risk(prediction_horizon_hours=-1)


@pytest.mark.parametrize(("dose_number", "amount"), [(0, 5.0), (1, 0.0), (1, -2.0)])
def test_dose_administration_rejects_impossible_values(dose_number, amount):
    with pytest.raises(ValidationError):
        DoseAdministration(
            dose_number=dose_number,
            administered_at=NOW,
            amount=amount,
            unit="mg",
        )


def test_observation_requires_a_known_measurement_type():
    """The vocabulary is closed: unknown measurements are rejected at the edge."""
    with pytest.raises(ValidationError):
        _observation(measurement_type="BLOOD_GLUCOSE")


# -- behaviour that lives on the contracts ---------------------------------


def test_treatment_tracks_dose_sequence():
    treatment = TreatmentAssignment(
        treatment_id="TX-1",
        patient_id="P-1042",
        trial_id="CT-001",
        screening_result_id="SR-abc",
        drug_name="Compound X",
        registered_at=NOW,
        doses=[
            DoseAdministration(dose_number=1, administered_at=NOW, amount=5, unit="mg"),
            DoseAdministration(
                dose_number=2,
                administered_at=NOW + timedelta(days=1),
                amount=5,
                unit="mg",
            ),
        ],
    )

    assert treatment.dose_count == 2
    assert treatment.next_dose_number == 3
    assert treatment.latest_dose.dose_number == 2
    assert treatment.status is TreatmentStatus.ACTIVE


def test_treatment_without_doses_proposes_the_first():
    treatment = TreatmentAssignment(
        treatment_id="TX-1",
        patient_id="P-1042",
        trial_id="CT-001",
        screening_result_id="SR-abc",
        drug_name="Compound X",
        registered_at=NOW,
    )

    assert treatment.dose_count == 0
    assert treatment.latest_dose is None
    assert treatment.next_dose_number == 1


def test_override_records_what_it_overrode():
    override = EligibilityOverride(
        approved_by="Dr. Chen",
        reason="EXC-01 disagreement reviewed; enrolment approved.",
        approved_at=NOW,
        screening_status=OverallStatus.REVIEW_REQUIRED,
    )
    assert override.screening_status is OverallStatus.REVIEW_REQUIRED


def test_adverse_event_is_active_until_resolved():
    event = AdverseEvent(
        event_id="AE-1",
        patient_id="P-1042",
        trial_id="CT-001",
        term="Nausea",
        severity=AdverseEventSeverity.MILD,
        onset_at=NOW,
    )
    assert event.is_active is True
    assert event.model_copy(update={"resolved_at": NOW}).is_active is False


def test_untrustworthy_data_quality_is_not_trustworthy():
    ok = DataQuality()
    degraded = DataQuality(
        status=DataQualityStatus.DEGRADED,
        flags=[
            DataQualityFlag(
                code=DataQualityCode.SPARSE_HISTORY,
                severity=Severity.INFO,
                message="Only two readings available.",
            )
        ],
    )
    untrustworthy = DataQuality(status=DataQualityStatus.UNTRUSTWORTHY)

    assert ok.is_trustworthy is True
    # DEGRADED still counts as usable — it means "say so", not "stop".
    assert degraded.is_trustworthy is True
    assert untrustworthy.is_trustworthy is False


def test_patient_state_looks_up_a_measurement():
    state = PatientState(
        patient_id="P-1042",
        trial_id="CT-001",
        as_of=NOW,
        measurements=[
            MeasurementSummary(
                measurement_type=MeasurementType.HEART_RATE,
                unit="bpm",
                baseline=70.0,
                current=88.0,
                delta_from_baseline=18.0,
                trend=TrendDirection.RISING,
                sample_count=12,
            )
        ],
    )

    found = state.measurement(MeasurementType.HEART_RATE)
    assert found is not None and found.trend is TrendDirection.RISING
    assert state.measurement(MeasurementType.SPO2) is None


def test_effective_risk_retains_the_provider_level_when_gated():
    """The gate must not erase what the model said."""
    effective = EffectiveRisk(
        level=RiskLevel.UNKNOWN,
        provider_level=RiskLevel.GREEN,
        gated=True,
        reason="Observations are stale; provider verdict not applied.",
    )

    assert effective.level is RiskLevel.UNKNOWN
    assert effective.provider_level is RiskLevel.GREEN
    assert effective.gated is True


def test_risk_transition_allows_no_previous_level():
    transition = RiskTransition(
        patient_id="P-1042",
        trial_id="CT-001",
        to_level=RiskLevel.GREEN,
        occurred_at=NOW,
    )
    assert transition.from_level is None


def test_next_dose_criterion_supports_unevaluable():
    """An unevaluable safety check is never silently counted as passed."""
    criterion = NextDoseCriterion(
        criterion_id="ND-03",
        description="SpO2 within protocol band",
        satisfied=None,
        detail="No SpO2 reading in the last 24 hours.",
    )
    assert criterion.satisfied is None


def test_notification_is_generated_but_not_delivered():
    notification = Notification(
        notification_id="NT-1",
        patient_id="P-1042",
        trial_id="CT-001",
        audience=NotificationAudience.CLINICIAN,
        channel=NotificationChannel.IN_APP,
        subject="Risk escalated to RED",
        body="Urgent review required.",
        created_at=NOW,
    )

    assert notification.is_delivered is False
    assert notification.delivery_provider is None


def test_intervention_carries_phase_one_evidence():
    """Phase 2 reuses the Phase 1 explainability primitive rather than inventing one."""
    intervention = Intervention(
        intervention_id="IV-1",
        patient_id="P-1042",
        trial_id="CT-001",
        raised_at=NOW,
        action=InterventionAction.INCREASE_MONITORING,
        severity=Severity.WARN,
        rationale="Heart rate rising against baseline.",
        protocol_rule_id="DEMO-AMBER-01",
        risk_level=RiskLevel.AMBER,
        monitoring_interval_minutes=15,
        evidence=[
            Evidence(
                source_type=EvidenceSource.RULE,
                locator="DEMO-AMBER-01",
                snippet="AMBER -> increase monitoring intensity",
            )
        ],
    )

    assert intervention.evidence[0].locator == "DEMO-AMBER-01"
    assert intervention.monitoring_interval_minutes == 15
