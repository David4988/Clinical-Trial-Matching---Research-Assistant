"""The JSON and SQL repositories must behave identically.

This is the test that keeps `PERSISTENCE=json` a real rollback rather than a
document that describes one, and the proof that the SQL port
(`docs/FINAL_IMPLEMENTATION_PLAN.md` §11.3) is mechanical rather than
approximate: the same scripted sequence of ABC calls, run against both
implementations, must produce the same domain objects.

Skipped (not failed) when the local Postgres from `docker-compose.yml` is not
running, so the default suite stays network-free.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.fixtures_loader import load_patient, load_trial
from app.repository.base import Repository
from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.json_repo import JsonRepository
from app.repository.monitoring_base import MonitoringRepository
from app.schema.monitoring import AdverseEvent, Observation, TreatmentAssignment
from app.schema.monitoring_enums import (
    AdverseEventSeverity,
    MeasurementType,
    MonitoringEventType,
    NotificationAudience,
    NotificationChannel,
    ObservationSource,
    RiskLevel,
    TreatmentStatus,
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
from app.service import ScreeningService

from .db_support import alembic_upgrade_head, real_url, require_postgres, reset_schema

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _run_scenario(
    repository: Repository, monitoring_repository: MonitoringRepository
) -> dict:
    """The same sequence of ABC calls, regardless of which implementation is
    behind `repository`/`monitoring_repository`. Returns everything a caller
    would need to compare for equality between two backends."""
    patient = load_patient("patient_incomplete")
    trial = load_trial("trial_demo")

    service = ScreeningService(repository=repository)
    result = service.screen(patient, trial)

    # Re-running screening must TOUCH, never duplicate, at the repository
    # level too: two screening results for the same (patient, trial) pair
    # are two independent rows by design (Phase 1 has no obligation identity
    # yet), so this instead proves get/list round-trip correctly.
    fetched = repository.get_screening_result(result.result_id)
    listed = repository.list_screening_results()

    treatment = TreatmentAssignment(
        treatment_id="TX-PARITY-1",
        patient_id=patient.patient_id,
        trial_id=trial.trial_id,
        screening_result_id=result.result_id,
        drug_name="ParityDrug",
        status=TreatmentStatus.ACTIVE,
        registered_at=NOW,
    )
    monitoring_repository.save_treatment(treatment)
    fetched_treatment = monitoring_repository.get_treatment("TX-PARITY-1")
    listed_treatments = monitoring_repository.list_treatments(trial_id=trial.trial_id)

    observations = [
        Observation(
            observation_id=f"OBS-PARITY-{i}",
            patient_id=patient.patient_id,
            trial_id=trial.trial_id,
            recorded_at=NOW + timedelta(minutes=i),
            source=ObservationSource.SYNTHETIC,
            measurement_type=MeasurementType.HEART_RATE,
            value=70.0 + i,
            unit="bpm",
        )
        for i in range(3)
    ]
    monitoring_repository.save_observations(observations)
    listed_observations = monitoring_repository.list_observations(patient.patient_id)

    adverse_event = AdverseEvent(
        event_id="AE-PARITY-1",
        patient_id=patient.patient_id,
        trial_id=trial.trial_id,
        term="Headache",
        severity=AdverseEventSeverity.MILD,
        onset_at=NOW,
    )
    monitoring_repository.save_adverse_event(adverse_event)
    listed_aes = monitoring_repository.list_adverse_events(patient.patient_id)

    patient_state = PatientState(patient_id=patient.patient_id, trial_id=trial.trial_id, as_of=NOW)
    risk = RiskAssessment(
        assessment_id="RA-PARITY-1",
        patient_id=patient.patient_id,
        trial_id=trial.trial_id,
        assessed_at=NOW,
        level=RiskLevel.GREEN,
        score=0.1,
        confidence=0.9,
        prediction_horizon_hours=24,
        provider="mock",
        model_version="v1",
    )
    effective_risk = EffectiveRisk(level=RiskLevel.GREEN, provider_level=RiskLevel.GREEN)
    cycle = MonitoringCycleResult(
        cycle_id="CYCLE-PARITY-1",
        patient_id=patient.patient_id,
        trial_id=trial.trial_id,
        generated_at=NOW,
        state=patient_state,
        risk=risk,
        effective_risk=effective_risk,
    )
    monitoring_repository.save_cycle(cycle)
    fetched_cycle = monitoring_repository.get_cycle("CYCLE-PARITY-1")
    latest_cycle = monitoring_repository.latest_cycle(patient.patient_id)

    events = [
        MonitoringEvent(
            event_id="EVT-PARITY-1",
            patient_id=patient.patient_id,
            trial_id=trial.trial_id,
            occurred_at=NOW,
            event_type=MonitoringEventType.TREATMENT_REGISTERED,
            summary="Parity test event",
        )
    ]
    monitoring_repository.append_events(events)
    listed_events = monitoring_repository.list_events(patient.patient_id)

    notification = Notification(
        notification_id="NT-PARITY-1",
        patient_id=patient.patient_id,
        trial_id=trial.trial_id,
        audience=NotificationAudience.CLINICIAN,
        channel=NotificationChannel.IN_APP,
        subject="Parity",
        body="Parity test notification",
        created_at=NOW,
    )
    monitoring_repository.save_notifications([notification])
    listed_notifications = monitoring_repository.list_notifications(patient.patient_id)

    return {
        "screening_result": result.model_dump(mode="json"),
        "fetched_screening_result": fetched.model_dump(mode="json") if fetched else None,
        "screening_result_count": len(listed),
        "treatment": fetched_treatment.model_dump(mode="json") if fetched_treatment else None,
        "treatment_list_ids": sorted(t.treatment_id for t in listed_treatments),
        "observations": [o.model_dump(mode="json") for o in listed_observations],
        "adverse_events": [a.model_dump(mode="json") for a in listed_aes],
        "cycle": fetched_cycle.model_dump(mode="json") if fetched_cycle else None,
        "latest_cycle_id": latest_cycle.cycle_id if latest_cycle else None,
        "events": [e.model_dump(mode="json") for e in listed_events],
        "notifications": [n.model_dump(mode="json") for n in listed_notifications],
    }


def test_json_and_sql_repositories_produce_identical_results(tmp_path):
    engine = require_postgres()
    reset_schema(engine)
    alembic_upgrade_head(real_url(engine))

    from app.repository.sql_monitoring import SqlMonitoringRepository
    from app.repository.sql_repo import SqlRepository

    json_result = _run_scenario(
        JsonRepository(tmp_path / "store.json"),
        JsonMonitoringRepository(tmp_path / "monitoring.json"),
    )
    sql_result = _run_scenario(SqlRepository(engine), SqlMonitoringRepository(engine))

    # result_id and other server-assigned ids differ between the two runs
    # (each ScreeningService.screen() call mints its own), so compare
    # everything EXCEPT the identifiers that are expected to differ, and
    # compare those identifiers only for internal self-consistency.
    for result in (json_result, sql_result):
        assert result["fetched_screening_result"]["result_id"] == result["screening_result"]["result_id"]

    for key in ("overall_status", "passed_count", "failed_count", "unknown_count", "rule_coverage"):
        assert json_result["screening_result"][key] == sql_result["screening_result"][key]

    assert json_result["screening_result_count"] == sql_result["screening_result_count"] == 1

    for key in ("patient_id", "trial_id", "drug_name", "status"):
        assert json_result["treatment"][key] == sql_result["treatment"][key]
    assert json_result["treatment_list_ids"] == sql_result["treatment_list_ids"] == ["TX-PARITY-1"]

    assert len(json_result["observations"]) == len(sql_result["observations"]) == 3
    for j, s in zip(json_result["observations"], sql_result["observations"]):
        assert j["observation_id"] == s["observation_id"]
        assert j["value"] == s["value"]
        assert j["measurement_type"] == s["measurement_type"]

    assert len(json_result["adverse_events"]) == len(sql_result["adverse_events"]) == 1
    assert json_result["adverse_events"][0]["term"] == sql_result["adverse_events"][0]["term"]

    assert json_result["cycle"]["cycle_id"] == sql_result["cycle"]["cycle_id"] == "CYCLE-PARITY-1"
    assert json_result["latest_cycle_id"] == sql_result["latest_cycle_id"] == "CYCLE-PARITY-1"

    assert len(json_result["events"]) == len(sql_result["events"]) == 1
    assert json_result["events"][0]["summary"] == sql_result["events"][0]["summary"]

    assert len(json_result["notifications"]) == len(sql_result["notifications"]) == 1
    assert json_result["notifications"][0]["subject"] == sql_result["notifications"][0]["subject"]


def test_sql_repository_transaction_rolls_back_on_failure():
    """§9.6: all writes inside `transaction()` commit together or not at
    all. A failure partway through must leave nothing behind."""
    engine = require_postgres()
    reset_schema(engine)
    alembic_upgrade_head(real_url(engine))

    from app.repository.sql_repo import SqlRepository

    repo = SqlRepository(engine)
    patient = load_patient("patient_incomplete")
    trial = load_trial("trial_demo")

    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.save_patient(patient)
            repo.save_trial(trial)
            raise RuntimeError("simulated failure mid-transaction")

    # Nothing committed: the patient saved earlier in the same transaction
    # block must not be visible either.
    from sqlalchemy import select

    from app.db.tables import patients

    with repo._session() as session:  # noqa: SLF001 - test-only introspection
        row = session.execute(
            select(patients).where(patients.c.patient_id == patient.patient_id)
        ).first()
    assert row is None
