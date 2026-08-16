"""M3: observation ingestion and data quality.

Covers the five validation categories the protocol requires: impossible values,
invalid units, missing observations, stale observations, conflicting
observations — plus the rule that nothing is silently dropped or converted.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring import protocol, quality
from app.monitoring.ingestion import ObservationIngestionService
from app.repository.json_monitoring import JsonMonitoringRepository
from app.schema.enums import Severity
from app.schema.monitoring import Observation
from app.schema.monitoring_enums import (
    DataQualityCode,
    DataQualityStatus,
    MeasurementType,
    MonitoringEventType,
    ObservationSource,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _obs(
    measurement_type=MeasurementType.HEART_RATE,
    value=72.0,
    unit="bpm",
    minutes_ago=0,
    patient="P-1042",
    obs_id=None,
) -> Observation:
    return Observation(
        observation_id=obs_id or f"OBS-{measurement_type.value}-{minutes_ago}-{value}",
        patient_id=patient,
        trial_id="CT-001",
        recorded_at=NOW - timedelta(minutes=minutes_ago),
        source=ObservationSource.SYNTHETIC,
        measurement_type=measurement_type,
        value=value,
        unit=unit,
    )


def _full_vitals(minutes_ago=0) -> list[Observation]:
    """One reading for every protocol-required measurement."""
    return [
        _obs(MeasurementType.HEART_RATE, 72.0, "bpm", minutes_ago),
        _obs(MeasurementType.SYSTOLIC_BP, 120.0, "mmHg", minutes_ago),
        _obs(MeasurementType.SPO2, 98.0, "%", minutes_ago),
    ]


def _record(minutes_ago=0, rounds=2) -> list[Observation]:
    """A complete record: several rounds of vitals, ten minutes apart.

    Deliberately more than SPARSE_HISTORY_BELOW readings, so these fixtures
    exercise the quality rule under test rather than tripping the sparse-history
    flag on the way in.
    """
    observations: list[Observation] = []
    for round_index in range(rounds):
        offset = minutes_ago + round_index * 10
        observations.extend(
            [
                _obs(MeasurementType.HEART_RATE, 72.0, "bpm", offset, obs_id=f"HR-{offset}"),
                _obs(MeasurementType.SYSTOLIC_BP, 120.0, "mmHg", offset, obs_id=f"SBP-{offset}"),
                _obs(MeasurementType.SPO2, 98.0, "%", offset, obs_id=f"SP-{offset}"),
            ]
        )
    return observations


@pytest.fixture
def store(tmp_path):
    return JsonMonitoringRepository(tmp_path / "monitoring.json")


@pytest.fixture
def ingestion(store):
    return ObservationIngestionService(store)


# -- impossible values -----------------------------------------------------


@pytest.mark.parametrize(
    ("measurement_type", "value"),
    [
        (MeasurementType.HEART_RATE, 900.0),
        (MeasurementType.HEART_RATE, 0.0),
        (MeasurementType.SPO2, 140.0),
        (MeasurementType.TEMPERATURE, 100.0),
        (MeasurementType.RESPIRATORY_RATE, 0.5),
        (MeasurementType.SYSTOLIC_BP, 400.0),
    ],
)
def test_impossible_values_are_refused(measurement_type, value):
    unit = protocol.EXPECTED_UNITS[measurement_type]
    reason = quality.check_observation(_obs(measurement_type, value, unit))

    assert reason is not None
    assert "recording error" in reason


def test_plausible_boundary_values_are_accepted():
    """The plausible range is inclusive at both ends."""
    low, high = protocol.PLAUSIBLE_RANGE[MeasurementType.HEART_RATE]

    assert quality.check_observation(_obs(value=low)) is None
    assert quality.check_observation(_obs(value=high)) is None


# -- invalid units ---------------------------------------------------------


def test_wrong_unit_is_refused_never_converted():
    reason = quality.check_observation(
        _obs(MeasurementType.TEMPERATURE, 98.6, "F")
    )

    assert reason is not None
    assert "No conversion applied" in reason


@pytest.mark.parametrize("unit", ["bpm", "BPM", "beats/min", "beats per minute"])
def test_notational_unit_variants_are_accepted(unit):
    assert quality.check_observation(_obs(unit=unit)) is None


@pytest.mark.parametrize("unit", ["%", "percent", "PCT"])
def test_spo2_unit_variants_are_accepted(unit):
    assert quality.check_observation(_obs(MeasurementType.SPO2, 98.0, unit)) is None


@pytest.mark.parametrize("unit", ["C", "°C", "celsius", "degC"])
def test_temperature_unit_variants_are_accepted(unit):
    assert quality.check_observation(_obs(MeasurementType.TEMPERATURE, 37.0, unit)) is None


# -- ingestion behaviour ---------------------------------------------------


def test_valid_batch_is_stored(ingestion, store):
    result = ingestion.ingest(_full_vitals(), now=NOW)

    assert result.accepted_count == 3
    assert result.rejected_count == 0
    assert result.patient_ids == ["P-1042"]
    assert len(store.list_observations("P-1042")) == 3


def test_invalid_rows_are_reported_not_silently_dropped(ingestion, store):
    batch = [*_full_vitals(), _obs(MeasurementType.HEART_RATE, 900.0, "bpm", obs_id="BAD-1")]

    result = ingestion.ingest(batch, now=NOW)

    assert result.accepted_count == 3
    assert result.rejected_count == 1
    assert result.rejected[0].observation.observation_id == "BAD-1"
    assert result.rejected[0].reason
    # The bad row never reached the store.
    assert len(store.list_observations("P-1042")) == 3


def test_a_fully_invalid_batch_stores_nothing_and_reports_everything(ingestion, store):
    batch = [
        _obs(MeasurementType.HEART_RATE, 900.0, "bpm", obs_id="B1"),
        _obs(MeasurementType.SPO2, 98.0, "kg", obs_id="B2"),
    ]

    result = ingestion.ingest(batch, now=NOW)

    assert result.accepted_count == 0
    assert result.rejected_count == 2
    assert store.list_observations("P-1042") == []


def test_ingestion_appends_one_timeline_event_per_patient(ingestion, store):
    ingestion.ingest(
        [*_full_vitals(), _obs(patient="P-2", obs_id="OBS-P2")], now=NOW
    )

    assert len(store.list_events("P-1042")) == 1
    assert len(store.list_events("P-2")) == 1
    assert (
        store.list_events("P-1042")[0].event_type
        is MonitoringEventType.OBSERVATIONS_INGESTED
    )


def test_empty_batch_is_harmless(ingestion, store):
    result = ingestion.ingest([], now=NOW)

    assert result.accepted_count == 0
    assert store.list_events("P-1042") == []


# -- record-level quality --------------------------------------------------


def test_complete_recent_record_is_ok():
    assessment = quality.assess(_record(), now=NOW)

    assert assessment.status is DataQualityStatus.OK
    assert assessment.is_trustworthy is True
    assert assessment.flags == []


def test_missing_required_measurement_is_untrustworthy():
    # SpO2 absent.
    observations = [
        _obs(MeasurementType.HEART_RATE, 72.0, "bpm"),
        _obs(MeasurementType.SYSTOLIC_BP, 120.0, "mmHg"),
    ]

    assessment = quality.assess(observations, now=NOW)

    assert assessment.status is DataQualityStatus.UNTRUSTWORTHY
    assert assessment.is_trustworthy is False
    codes = {f.code for f in assessment.flags}
    assert DataQualityCode.MISSING_MEASUREMENT in codes


def test_stale_observations_are_untrustworthy():
    """Old readings cannot support a current verdict."""
    stale_minutes = int(protocol.STALE_AFTER.total_seconds() // 60) + 30

    assessment = quality.assess(_record(minutes_ago=stale_minutes), now=NOW)

    assert assessment.status is DataQualityStatus.UNTRUSTWORTHY
    codes = {f.code for f in assessment.flags}
    assert DataQualityCode.STALE_OBSERVATION in codes


def test_readings_just_inside_the_staleness_window_are_fine():
    fresh = int(protocol.STALE_AFTER.total_seconds() // 60) - 5

    assessment = quality.assess(_record(minutes_ago=fresh), now=NOW)

    assert assessment.status is DataQualityStatus.OK


def test_conflicting_observations_are_flagged_but_still_usable():
    """Mirrors Phase 1: contradictions are surfaced, latest value still used."""
    observations = [
        *_record(),
        # A second heart rate at the same instant, wildly different.
        _obs(MeasurementType.HEART_RATE, 150.0, "bpm", minutes_ago=0, obs_id="OBS-CONFLICT"),
    ]

    assessment = quality.assess(observations, now=NOW)

    codes = {f.code for f in assessment.flags}
    assert DataQualityCode.CONFLICTING_OBSERVATIONS in codes
    assert assessment.status is DataQualityStatus.DEGRADED
    # Degraded still counts as usable — it means "say so", not "stop".
    assert assessment.is_trustworthy is True


def test_near_identical_repeat_readings_are_not_conflicting():
    observations = [
        *_record(),
        _obs(MeasurementType.HEART_RATE, 73.0, "bpm", minutes_ago=0, obs_id="OBS-REPEAT"),
    ]

    assessment = quality.assess(observations, now=NOW)

    codes = {f.code for f in assessment.flags}
    assert DataQualityCode.CONFLICTING_OBSERVATIONS not in codes


def test_widely_spaced_differing_readings_are_a_trend_not_a_conflict():
    """A heart rate that climbs over an hour is a trajectory, not a contradiction.

    Built explicitly rather than from _record(), because two readings at the
    *same* instant would be a genuine conflict and would not test this rule.
    """
    observations = [
        _obs(MeasurementType.HEART_RATE, 72.0, "bpm", 60, obs_id="HR-old"),
        _obs(MeasurementType.HEART_RATE, 150.0, "bpm", 0, obs_id="HR-new"),
        _obs(MeasurementType.SYSTOLIC_BP, 120.0, "mmHg", 60, obs_id="SBP-old"),
        _obs(MeasurementType.SYSTOLIC_BP, 122.0, "mmHg", 0, obs_id="SBP-new"),
        _obs(MeasurementType.SPO2, 98.0, "%", 60, obs_id="SP-old"),
        _obs(MeasurementType.SPO2, 97.0, "%", 0, obs_id="SP-new"),
    ]

    assessment = quality.assess(observations, now=NOW)

    codes = {f.code for f in assessment.flags}
    assert DataQualityCode.CONFLICTING_OBSERVATIONS not in codes


def test_sparse_history_is_flagged_as_a_caveat_not_a_blocker():
    """An INFO flag degrades the record but must never make it untrustworthy."""
    assessment = quality.assess(_full_vitals(), now=NOW)  # only three readings

    sparse = [f for f in assessment.flags if f.code is DataQualityCode.SPARSE_HISTORY]
    assert len(sparse) == 1
    assert sparse[0].severity is Severity.INFO
    assert assessment.status is DataQualityStatus.DEGRADED
    assert assessment.is_trustworthy is True


def test_empty_record_is_untrustworthy():
    assessment = quality.assess([], now=NOW)

    assert assessment.status is DataQualityStatus.UNTRUSTWORTHY
    assert assessment.is_trustworthy is False


def test_flags_name_the_measurements_they_concern():
    observations = [_obs(MeasurementType.HEART_RATE, 72.0, "bpm")]

    assessment = quality.assess(observations, now=NOW)
    missing = next(
        f for f in assessment.flags if f.code is DataQualityCode.MISSING_MEASUREMENT
    )

    assert MeasurementType.SPO2 in missing.measurement_types
    assert MeasurementType.SYSTOLIC_BP in missing.measurement_types
