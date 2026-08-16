"""M4: the Patient State Engine.

Trend and baseline maths against hand-built series, plus the determinism and
purity properties the rest of Phase 2 relies on.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring import protocol
from app.monitoring.state import build_patient_state
from app.schema.monitoring import AdverseEvent, Observation, TreatmentAssignment
from app.schema.monitoring_enums import (
    AdverseEventSeverity,
    DataQualityStatus,
    MeasurementType,
    ObservationSource,
    TrendDirection,
)

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def _obs(
    measurement_type: MeasurementType,
    value: float,
    unit: str,
    minutes_ago: float,
    trial="CT-001",
    index=0,
) -> Observation:
    return Observation(
        observation_id=f"OBS-{measurement_type.value}-{minutes_ago}-{index}",
        patient_id="P-1042",
        trial_id=trial,
        recorded_at=NOW - timedelta(minutes=minutes_ago),
        source=ObservationSource.SYNTHETIC,
        measurement_type=measurement_type,
        value=value,
        unit=unit,
    )


def _series(values: list[float], measurement_type=MeasurementType.HEART_RATE,
            unit="bpm", step_minutes=20) -> list[Observation]:
    """Oldest first: values[0] is the earliest reading."""
    total = len(values)
    return [
        _obs(measurement_type, value, unit, (total - 1 - i) * step_minutes, index=i)
        for i, value in enumerate(values)
    ]


def _state(observations, **kwargs):
    return build_patient_state(
        patient_id="P-1042",
        trial_id="CT-001",
        observations=observations,
        now=NOW,
        **kwargs,
    )


# -- purity and determinism ------------------------------------------------


def test_state_is_deterministic():
    observations = _series([70, 72, 74, 76])

    first = _state(observations)
    second = _state(observations)

    assert first.model_dump() == second.model_dump()


def test_state_does_not_mutate_its_inputs():
    observations = _series([70, 72, 74])
    before = [o.model_dump() for o in observations]

    _state(observations)

    assert [o.model_dump() for o in observations] == before


def test_as_of_is_the_supplied_clock_not_wall_time():
    state = _state(_series([70, 72, 74]))
    assert state.as_of == NOW


# -- current and baseline --------------------------------------------------


def test_current_is_the_latest_reading():
    state = _state(_series([70, 80, 90, 100]))
    heart_rate = state.measurement(MeasurementType.HEART_RATE)

    assert heart_rate.current == 100
    assert heart_rate.latest_at == NOW


def test_baseline_is_the_patients_own_earliest_readings():
    """A trial patient is their own control, not compared to a population norm."""
    state = _state(_series([60, 62, 64, 100, 120]))
    heart_rate = state.measurement(MeasurementType.HEART_RATE)

    # BASELINE_SAMPLE_COUNT is 5, so all five readings form the baseline here.
    expected = (60 + 62 + 64 + 100 + 120) / 5
    assert heart_rate.baseline == pytest.approx(expected)


def test_baseline_uses_only_the_first_n_readings():
    values = [60] * protocol.BASELINE_SAMPLE_COUNT + [200] * 5
    state = _state(_series(values))
    heart_rate = state.measurement(MeasurementType.HEART_RATE)

    assert heart_rate.baseline == pytest.approx(60.0)
    assert heart_rate.current == 200
    assert heart_rate.delta_from_baseline == pytest.approx(140.0)


def test_sample_count_reflects_every_reading():
    state = _state(_series([70, 71, 72, 73, 74, 75]))
    assert state.measurement(MeasurementType.HEART_RATE).sample_count == 6
    assert state.observation_count == 6


# -- trends ----------------------------------------------------------------


def test_rising_series_is_rising():
    state = _state(_series([70, 80, 90, 100]))
    assert state.measurement(MeasurementType.HEART_RATE).trend is TrendDirection.RISING


def test_falling_series_is_falling():
    state = _state(_series([110, 100, 90, 80]))
    assert state.measurement(MeasurementType.HEART_RATE).trend is TrendDirection.FALLING


def test_flat_series_is_stable():
    state = _state(_series([72, 72, 72, 72]))
    assert state.measurement(MeasurementType.HEART_RATE).trend is TrendDirection.STABLE


def test_tiny_drift_is_stable_not_rising():
    """Noise must not read as a trajectory."""
    state = _state(_series([72.0, 72.1, 72.0, 72.2], step_minutes=20))
    assert state.measurement(MeasurementType.HEART_RATE).trend is TrendDirection.STABLE


def test_too_few_readings_is_insufficient_data_not_stable():
    """'Flat' and 'we cannot tell' must stay distinguishable."""
    state = _state(_series([70, 90]))
    heart_rate = state.measurement(MeasurementType.HEART_RATE)

    assert heart_rate.trend is TrendDirection.INSUFFICIENT_DATA
    assert heart_rate.slope_per_hour is None


def test_readings_all_at_one_instant_have_no_trend():
    observations = [
        _obs(MeasurementType.HEART_RATE, value, "bpm", 0, index=i)
        for i, value in enumerate([70, 80, 90])
    ]

    state = _state(observations)
    heart_rate = state.measurement(MeasurementType.HEART_RATE)

    assert heart_rate.slope_per_hour is None
    assert heart_rate.trend is TrendDirection.INSUFFICIENT_DATA


def test_slope_is_reported_per_hour():
    # +10 bpm every 30 minutes == +20 bpm/hour.
    state = _state(_series([70, 80, 90, 100], step_minutes=30))
    assert state.measurement(MeasurementType.HEART_RATE).slope_per_hour == pytest.approx(
        20.0, rel=1e-3
    )


def test_flat_threshold_is_scaled_per_measurement():
    """The same absolute drift is noise for heart rate and a trend for temperature."""
    drift = 0.2  # units per reading

    hr = _state(_series([72 + drift * i for i in range(4)]))
    temp = _state(
        _series(
            [37.0 + drift * i for i in range(4)],
            measurement_type=MeasurementType.TEMPERATURE,
            unit="C",
        )
    )

    assert hr.measurement(MeasurementType.HEART_RATE).trend is TrendDirection.STABLE
    assert temp.measurement(MeasurementType.TEMPERATURE).trend is TrendDirection.RISING


def test_trend_uses_only_the_recent_window():
    """A spike from yesterday must not drive today's trend."""
    old = _obs(MeasurementType.HEART_RATE, 200.0, "bpm", 60 * 24, index=99)
    recent = _series([72, 72, 72, 72], step_minutes=10)

    state = _state([old, *recent])
    heart_rate = state.measurement(MeasurementType.HEART_RATE)

    assert heart_rate.trend is TrendDirection.STABLE
    assert heart_rate.sample_count == 5  # the old reading still counts as history


# -- staleness -------------------------------------------------------------


def test_stale_measurement_is_marked():
    """Every reading older than the staleness window, newest included."""
    stale_minutes = int(protocol.STALE_AFTER.total_seconds() // 60) + 60
    observations = [
        _obs(MeasurementType.HEART_RATE, 70.0 + i, "bpm", stale_minutes + i * 5, index=i)
        for i in range(3)
    ]

    state = _state(observations)

    assert state.measurement(MeasurementType.HEART_RATE).is_stale is True


def test_fresh_measurement_is_not_stale():
    state = _state(_series([70, 72, 74], step_minutes=5))
    assert state.measurement(MeasurementType.HEART_RATE).is_stale is False


# -- composition -----------------------------------------------------------


def test_multiple_measurement_types_are_summarised_independently():
    observations = [
        *_series([70, 80, 90, 100]),
        *_series([98, 97, 96, 95], MeasurementType.SPO2, "%"),
    ]

    state = _state(observations)

    assert state.measurement(MeasurementType.HEART_RATE).trend is TrendDirection.RISING
    assert state.measurement(MeasurementType.SPO2).trend is TrendDirection.FALLING
    assert len(state.measurements) == 2


def test_observations_from_another_trial_are_excluded():
    observations = [
        *_series([70, 72, 74]),
        _obs(MeasurementType.HEART_RATE, 999.0, "bpm", 5, trial="CT-OTHER", index=42),
    ]

    state = _state(observations)

    assert state.observation_count == 3
    assert state.measurement(MeasurementType.HEART_RATE).current == 74


def test_treatment_and_active_adverse_events_are_attached():
    treatment = TreatmentAssignment(
        treatment_id="TX-1",
        patient_id="P-1042",
        trial_id="CT-001",
        screening_result_id="SR-1",
        drug_name="Compound X",
        registered_at=NOW,
    )
    events = [
        AdverseEvent(
            event_id="AE-1",
            patient_id="P-1042",
            trial_id="CT-001",
            term="Nausea",
            severity=AdverseEventSeverity.MILD,
            onset_at=NOW,
        ),
        AdverseEvent(
            event_id="AE-2",
            patient_id="P-1042",
            trial_id="CT-001",
            term="Headache",
            severity=AdverseEventSeverity.MILD,
            onset_at=NOW - timedelta(days=2),
            resolved_at=NOW - timedelta(days=1),
        ),
    ]

    state = _state(_series([70, 72, 74]), treatment=treatment, adverse_events=events)

    assert state.treatment.treatment_id == "TX-1"
    # Only the unresolved event is active.
    assert [e.event_id for e in state.active_adverse_events] == ["AE-1"]


def test_state_carries_data_quality():
    state = _state(_series([70, 72, 74]))
    # Heart rate only — the protocol also requires systolic BP and SpO2.
    assert state.data_quality.status is DataQualityStatus.UNTRUSTWORTHY


def test_empty_record_produces_an_empty_but_valid_state():
    state = _state([])

    assert state.measurements == []
    assert state.observation_count == 0
    assert state.data_quality.is_trustworthy is False


def test_recent_observations_are_bounded():
    state = _state(_series([70.0 + i * 0.001 for i in range(200)], step_minutes=1))

    assert len(state.recent_observations) == protocol.RECENT_OBSERVATION_LIMIT
    assert state.observation_count == 200
    # The bounded window keeps the newest readings.
    assert state.recent_observations[-1].recorded_at == NOW
