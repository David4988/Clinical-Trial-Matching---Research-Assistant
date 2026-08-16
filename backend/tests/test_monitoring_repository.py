"""M1: the monitoring store.

Fixtures are defined locally rather than in `conftest.py` so the Phase 1 test
configuration stays untouched.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.monitoring_base import MonitoringRepository
from app.schema.enums import OverallStatus
from app.schema.monitoring import (
    AdverseEvent,
    DoseAdministration,
    EligibilityOverride,
    Observation,
    TreatmentAssignment,
)
from app.schema.monitoring_enums import (
    AdverseEventSeverity,
    MeasurementType,
    MonitoringEventType,
    NotificationAudience,
    NotificationChannel,
    ObservationSource,
    RiskLevel,
)
from app.schema.monitoring_result import (
    DataQuality,
    EffectiveRisk,
    MonitoringCycleResult,
    MonitoringEvent,
    Notification,
    PatientState,
    RiskAssessment,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path) -> JsonMonitoringRepository:
    return JsonMonitoringRepository(tmp_path / "monitoring.json")


def _observation(index: int, *, minutes: int = 0, patient="P-1042") -> Observation:
    return Observation(
        observation_id=f"OBS-{index}",
        patient_id=patient,
        trial_id="CT-001",
        recorded_at=NOW + timedelta(minutes=minutes),
        source=ObservationSource.SYNTHETIC,
        measurement_type=MeasurementType.HEART_RATE,
        value=70.0 + index,
        unit="bpm",
    )


def _treatment(treatment_id="TX-1", patient="P-1042", trial="CT-001") -> TreatmentAssignment:
    return TreatmentAssignment(
        treatment_id=treatment_id,
        patient_id=patient,
        trial_id=trial,
        screening_result_id="SR-abc",
        drug_name="Compound X",
        registered_at=NOW,
        doses=[DoseAdministration(dose_number=1, administered_at=NOW, amount=5, unit="mg")],
    )


def _cycle(cycle_id="CY-1", *, hours: int = 0, level=RiskLevel.GREEN) -> MonitoringCycleResult:
    at = NOW + timedelta(hours=hours)
    return MonitoringCycleResult(
        cycle_id=cycle_id,
        patient_id="P-1042",
        trial_id="CT-001",
        generated_at=at,
        state=PatientState(
            patient_id="P-1042",
            trial_id="CT-001",
            as_of=at,
            data_quality=DataQuality(),
        ),
        risk=RiskAssessment(
            assessment_id=f"RA-{cycle_id}",
            patient_id="P-1042",
            trial_id="CT-001",
            assessed_at=at,
            level=level,
            score=0.2,
            confidence=0.8,
            prediction_horizon_hours=24,
            provider="mock-risk-v1",
            model_version="0.1.0",
        ),
        effective_risk=EffectiveRisk(level=level, provider_level=level),
    )


# -- interface -------------------------------------------------------------


def test_json_store_implements_the_interface():
    assert issubclass(JsonMonitoringRepository, MonitoringRepository)


def test_phase_one_repository_is_not_involved(store):
    """The monitoring store must not be a Repository — the interfaces are siblings."""
    from app.repository.base import Repository

    assert not isinstance(store, Repository)


# -- treatments ------------------------------------------------------------


def test_treatment_round_trip(store):
    store.save_treatment(_treatment())
    fetched = store.get_treatment("TX-1")

    assert fetched is not None
    assert fetched.drug_name == "Compound X"
    assert fetched.dose_count == 1
    assert fetched.registered_at == NOW


def test_treatment_override_survives_round_trip(store):
    treatment = _treatment().model_copy(
        update={
            "override": EligibilityOverride(
                approved_by="Dr. Chen",
                reason="EXC-01 disagreement reviewed.",
                approved_at=NOW,
                screening_status=OverallStatus.REVIEW_REQUIRED,
            )
        }
    )
    store.save_treatment(treatment)

    fetched = store.get_treatment("TX-1")
    assert fetched.override is not None
    assert fetched.override.approved_by == "Dr. Chen"
    assert fetched.override.screening_status is OverallStatus.REVIEW_REQUIRED


def test_unknown_treatment_is_none(store):
    assert store.get_treatment("TX-nope") is None


def test_list_treatments_filters_by_trial_and_patient(store):
    store.save_treatment(_treatment("TX-1", patient="P-1", trial="CT-001"))
    store.save_treatment(_treatment("TX-2", patient="P-2", trial="CT-001"))
    store.save_treatment(_treatment("TX-3", patient="P-3", trial="CT-999"))

    assert len(store.list_treatments()) == 3
    assert len(store.list_treatments(trial_id="CT-001")) == 2
    assert len(store.list_treatments(patient_id="P-2")) == 1
    assert store.list_treatments(trial_id="CT-999")[0].patient_id == "P-3"


# -- observations ----------------------------------------------------------


def test_observations_round_trip_in_chronological_order(store):
    # Saved out of order on purpose.
    store.save_observations([_observation(3, minutes=30), _observation(1, minutes=0)])
    store.save_observations([_observation(2, minutes=15)])

    observations = store.list_observations("P-1042")
    assert [o.observation_id for o in observations] == ["OBS-1", "OBS-2", "OBS-3"]


def test_observations_are_bucketed_per_patient(store):
    store.save_observations([_observation(1, patient="P-A"), _observation(2, patient="P-B")])

    assert len(store.list_observations("P-A")) == 1
    assert len(store.list_observations("P-B")) == 1
    assert store.list_observations("P-C") == []


def test_observations_filter_by_since(store):
    store.save_observations([_observation(i, minutes=i * 10) for i in range(4)])

    recent = store.list_observations("P-1042", since=NOW + timedelta(minutes=15))
    assert [o.observation_id for o in recent] == ["OBS-2", "OBS-3"]


def test_empty_batch_is_a_no_op(store):
    store.save_observations([])
    assert store.list_observations("P-1042") == []


def test_batch_save_writes_once_regardless_of_size(store, monkeypatch):
    """The guarantee that keeps high-frequency ingestion viable.

    A per-row write would rewrite the whole JSON store 50 times here.
    """
    writes = []
    original = store._write
    monkeypatch.setattr(store, "_write", lambda data: (writes.append(1), original(data))[1])

    store.save_observations([_observation(i, minutes=i) for i in range(50)])

    assert len(writes) == 1
    assert len(store.list_observations("P-1042")) == 50


def test_observations_survive_a_new_repository_instance(tmp_path):
    path = tmp_path / "monitoring.json"
    JsonMonitoringRepository(path).save_observations([_observation(1)])

    reopened = JsonMonitoringRepository(path)
    assert len(reopened.list_observations("P-1042")) == 1


# -- adverse events --------------------------------------------------------


def _adverse_event(resolved=None) -> AdverseEvent:
    return AdverseEvent(
        event_id="AE-1",
        patient_id="P-1042",
        trial_id="CT-001",
        term="Nausea",
        severity=AdverseEventSeverity.MILD,
        onset_at=NOW,
        resolved_at=resolved,
    )


def test_adverse_event_round_trip(store):
    store.save_adverse_event(_adverse_event())
    events = store.list_adverse_events("P-1042")

    assert len(events) == 1
    assert events[0].is_active is True


def test_resolving_an_adverse_event_updates_rather_than_duplicates(store):
    store.save_adverse_event(_adverse_event())
    store.save_adverse_event(_adverse_event(resolved=NOW + timedelta(hours=6)))

    events = store.list_adverse_events("P-1042")
    assert len(events) == 1
    assert events[0].is_active is False


# -- cycles ----------------------------------------------------------------


def test_cycle_round_trip_preserves_the_full_decision_record(store):
    store.save_cycle(_cycle())
    fetched = store.get_cycle("CY-1")

    assert fetched is not None
    assert fetched.risk.provider == "mock-risk-v1"
    assert fetched.effective_risk.level is RiskLevel.GREEN
    assert fetched.state.patient_id == "P-1042"


def test_latest_cycle_returns_the_most_recent(store):
    store.save_cycle(_cycle("CY-1", hours=0, level=RiskLevel.GREEN))
    store.save_cycle(_cycle("CY-2", hours=2, level=RiskLevel.AMBER))
    store.save_cycle(_cycle("CY-3", hours=1, level=RiskLevel.RED))

    latest = store.latest_cycle("P-1042")
    assert latest.cycle_id == "CY-2"  # newest by generated_at, not insertion order


def test_list_cycles_is_newest_first(store):
    store.save_cycle(_cycle("CY-1", hours=0))
    store.save_cycle(_cycle("CY-2", hours=5))

    assert [c.cycle_id for c in store.list_cycles()] == ["CY-2", "CY-1"]


def test_latest_cycle_for_unknown_patient_is_none(store):
    assert store.latest_cycle("P-nobody") is None


# -- timeline --------------------------------------------------------------


def _event(index: int, minutes: int) -> MonitoringEvent:
    return MonitoringEvent(
        event_id=f"EV-{index}",
        patient_id="P-1042",
        trial_id="CT-001",
        occurred_at=NOW + timedelta(minutes=minutes),
        event_type=MonitoringEventType.RISK_ASSESSED,
        summary=f"event {index}",
    )


def test_events_are_appended_and_read_oldest_first(store):
    store.append_events([_event(2, 20)])
    store.append_events([_event(1, 10), _event(3, 30)])

    assert [e.event_id for e in store.list_events("P-1042")] == ["EV-1", "EV-2", "EV-3"]


def test_appending_never_rewrites_existing_entries(store):
    store.append_events([_event(1, 10)])
    store.append_events([_event(1, 10)])

    # Same id appended twice yields two rows: the log is append-only, not a map.
    assert len(store.list_events("P-1042")) == 2


def test_empty_event_batch_is_a_no_op(store):
    store.append_events([])
    assert store.list_events("P-1042") == []


# -- notifications ---------------------------------------------------------


def test_notifications_round_trip_newest_first(store):
    store.save_notifications(
        [
            Notification(
                notification_id=f"NT-{i}",
                patient_id="P-1042",
                trial_id="CT-001",
                audience=NotificationAudience.CLINICIAN,
                channel=NotificationChannel.IN_APP,
                subject=f"alert {i}",
                body="body",
                created_at=NOW + timedelta(minutes=i * 10),
            )
            for i in range(3)
        ]
    )

    notifications = store.list_notifications("P-1042")
    assert [n.notification_id for n in notifications] == ["NT-2", "NT-1", "NT-0"]
    assert all(n.is_delivered is False for n in notifications)


# -- failure modes ---------------------------------------------------------


def test_corrupt_store_raises_repository_error(tmp_path):
    from app.repository.base import RepositoryError

    path = tmp_path / "monitoring.json"
    path.write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(RepositoryError):
        JsonMonitoringRepository(path).list_treatments()


def test_monitoring_store_is_separate_from_the_screening_store(tmp_path):
    """Observation traffic must never rewrite Phase 1 screening results."""
    from app.repository.json_repo import JsonRepository

    screening_path = tmp_path / "store.json"
    monitoring_path = tmp_path / "monitoring.json"

    JsonRepository(screening_path)
    monitoring = JsonMonitoringRepository(monitoring_path)
    monitoring.save_observations([_observation(1)])

    assert monitoring_path.exists()
    # Phase 1's store was never created by monitoring writes.
    assert not screening_path.exists()
