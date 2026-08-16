"""M2: the Phase 1 -> Phase 2 doorway.

Uses the real Phase 1 screening service to produce the screening results these
tests gate on, so the bridge is exercised end to end rather than against a stub.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.fixtures_loader import load_patient, load_trial
from app.monitoring.errors import MonitoringError
from app.monitoring.treatment import TreatmentService
from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.json_repo import JsonRepository
from app.schema.enums import OverallStatus
from app.schema.monitoring_enums import MonitoringEventType, TreatmentStatus
from app.service import ScreeningService

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def context(tmp_path):
    """A screening store, a monitoring store, and the services over them."""
    screening_repo = JsonRepository(tmp_path / "store.json")
    monitoring_repo = JsonMonitoringRepository(tmp_path / "monitoring.json")
    return {
        "screening": ScreeningService(repository=screening_repo),
        "treatment": TreatmentService(screening_repo, monitoring_repo),
        "monitoring_repo": monitoring_repo,
    }


def _screen(context, patient: str, trial: str):
    return context["screening"].screen(load_patient(patient), load_trial(trial))


def _eligible(context):
    result = _screen(context, "patient_eligible", "trial_supported")
    assert result.overall_status is OverallStatus.ELIGIBLE
    return result


def _review_required(context):
    result = _screen(context, "patient_pdf_demo", "trial_demo")
    assert result.overall_status is OverallStatus.REVIEW_REQUIRED
    return result


def _ineligible(context):
    result = _screen(context, "patient_ineligible", "trial_supported")
    assert result.overall_status is OverallStatus.INELIGIBLE
    return result


# -- the gate --------------------------------------------------------------


def test_eligible_patient_registers_without_an_override(context):
    screening = _eligible(context)

    treatment = context["treatment"].register(
        screening_result_id=screening.result_id,
        drug_name="Compound X",
        now=NOW,
    )

    assert treatment.status is TreatmentStatus.ACTIVE
    assert treatment.override is None
    assert treatment.dose_count == 0


def test_review_required_is_refused_without_an_override(context):
    screening = _review_required(context)

    with pytest.raises(MonitoringError) as exc:
        context["treatment"].register(
            screening_result_id=screening.result_id,
            drug_name="Compound X",
            now=NOW,
        )

    assert exc.value.code == "OVERRIDE_REQUIRED"
    assert exc.value.details


@pytest.mark.parametrize(
    ("by", "reason"),
    [(None, "reviewed"), ("Dr. Chen", None), ("", "reviewed"), ("Dr. Chen", "   ")],
)
def test_override_requires_both_a_named_clinician_and_a_reason(context, by, reason):
    screening = _review_required(context)

    with pytest.raises(MonitoringError) as exc:
        context["treatment"].register(
            screening_result_id=screening.result_id,
            drug_name="Compound X",
            now=NOW,
            override_by=by,
            override_reason=reason,
        )

    assert exc.value.code == "OVERRIDE_REQUIRED"


def test_review_required_registers_with_a_recorded_override(context):
    screening = _review_required(context)

    treatment = context["treatment"].register(
        screening_result_id=screening.result_id,
        drug_name="Compound X",
        now=NOW,
        override_by="Dr. Chen",
        override_reason="EXC-01 rule/AI disagreement reviewed; enrolment approved.",
    )

    assert treatment.override is not None
    assert treatment.override.approved_by == "Dr. Chen"
    assert treatment.override.screening_status is OverallStatus.REVIEW_REQUIRED
    assert treatment.override.approved_at == NOW


def test_ineligible_patient_is_always_refused(context):
    screening = _ineligible(context)

    with pytest.raises(MonitoringError) as exc:
        context["treatment"].register(
            screening_result_id=screening.result_id,
            drug_name="Compound X",
            now=NOW,
            override_by="Dr. Chen",
            override_reason="wants to enrol anyway",
        )

    assert exc.value.code == "TREATMENT_NOT_PERMITTED"


def test_override_is_not_stored_when_screening_was_eligible(context):
    """An override on an ELIGIBLE screening is noise in the audit trail."""
    screening = _eligible(context)

    treatment = context["treatment"].register(
        screening_result_id=screening.result_id,
        drug_name="Compound X",
        now=NOW,
        override_by="Dr. Chen",
        override_reason="not needed",
    )

    assert treatment.override is None


def test_unknown_screening_result_is_rejected(context):
    with pytest.raises(MonitoringError) as exc:
        context["treatment"].register(
            screening_result_id="SR-does-not-exist",
            drug_name="Compound X",
            now=NOW,
        )

    assert exc.value.code == "SCREENING_NOT_FOUND"


# -- identity --------------------------------------------------------------


def test_patient_identity_comes_from_the_screening_result(context):
    """Phase 2 must not re-enter or duplicate identity."""
    screening = _eligible(context)

    treatment = context["treatment"].register(
        screening_result_id=screening.result_id,
        drug_name="Compound X",
        now=NOW,
    )

    assert treatment.patient_id == screening.patient.patient_id
    assert treatment.trial_id == screening.trial.trial_id
    assert treatment.screening_result_id == screening.result_id


def test_second_active_treatment_on_the_same_trial_is_refused(context):
    screening = _eligible(context)
    context["treatment"].register(
        screening_result_id=screening.result_id, drug_name="Compound X", now=NOW
    )

    with pytest.raises(MonitoringError) as exc:
        context["treatment"].register(
            screening_result_id=screening.result_id, drug_name="Compound Y", now=NOW
        )

    assert exc.value.code == "TREATMENT_ALREADY_ACTIVE"


# -- timeline --------------------------------------------------------------


def test_registration_appends_a_timeline_event(context):
    screening = _eligible(context)
    treatment = context["treatment"].register(
        screening_result_id=screening.result_id, drug_name="Compound X", now=NOW
    )

    events = context["monitoring_repo"].list_events(treatment.patient_id)
    assert [e.event_type for e in events] == [MonitoringEventType.TREATMENT_REGISTERED]
    assert events[0].ref_id == treatment.treatment_id


def test_override_is_recorded_as_its_own_timeline_event(context):
    screening = _review_required(context)
    treatment = context["treatment"].register(
        screening_result_id=screening.result_id,
        drug_name="Compound X",
        now=NOW,
        override_by="Dr. Chen",
        override_reason="Reviewed.",
    )

    types = [e.event_type for e in context["monitoring_repo"].list_events(treatment.patient_id)]
    assert MonitoringEventType.ELIGIBILITY_OVERRIDE_RECORDED in types


# -- doses -----------------------------------------------------------------


def test_doses_are_numbered_in_sequence(context):
    screening = _eligible(context)
    service = context["treatment"]
    treatment = service.register(
        screening_result_id=screening.result_id, drug_name="Compound X", now=NOW
    )

    service.record_dose(treatment.treatment_id, amount=5, unit="mg", now=NOW)
    updated = service.record_dose(
        treatment.treatment_id, amount=5, unit="mg", now=NOW + timedelta(days=1)
    )

    assert [d.dose_number for d in updated.doses] == [1, 2]
    assert updated.next_dose_number == 3
    assert updated.latest_dose.administered_at == NOW + timedelta(days=1)


def test_dose_appends_a_timeline_event(context):
    screening = _eligible(context)
    service = context["treatment"]
    treatment = service.register(
        screening_result_id=screening.result_id, drug_name="Compound X", now=NOW
    )
    service.record_dose(treatment.treatment_id, amount=5, unit="mg", now=NOW)

    types = [e.event_type for e in context["monitoring_repo"].list_events(treatment.patient_id)]
    assert MonitoringEventType.DOSE_ADMINISTERED in types


def test_dose_on_a_held_treatment_is_refused(context):
    screening = _eligible(context)
    service = context["treatment"]
    treatment = service.register(
        screening_result_id=screening.result_id, drug_name="Compound X", now=NOW
    )
    service.set_status(treatment.treatment_id, TreatmentStatus.ON_HOLD)

    with pytest.raises(MonitoringError) as exc:
        service.record_dose(treatment.treatment_id, amount=5, unit="mg", now=NOW)

    assert exc.value.code == "TREATMENT_NOT_ACTIVE"


def test_dose_on_unknown_treatment_is_refused(context):
    with pytest.raises(MonitoringError) as exc:
        context["treatment"].record_dose("TX-nope", amount=5, unit="mg", now=NOW)

    assert exc.value.code == "TREATMENT_NOT_FOUND"
