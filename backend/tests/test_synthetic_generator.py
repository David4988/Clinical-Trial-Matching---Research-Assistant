"""M5: the synthetic data generator.

The properties that matter: reproducible from a seed, longitudinal rather than
independent rows, and self-labelling as synthetic.
"""

from datetime import datetime, timezone

import pytest

from app.monitoring import quality
from app.schema.monitoring_enums import MeasurementType, ObservationSource
from app.synthetic.generator import (
    COHORT,
    Trajectory,
    generate_cohort,
    generate_observations,
    generate_windowed,
)

START = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)


def _generate(trajectory=Trajectory.STABLE, seed=7, **kwargs):
    return generate_observations(
        "P-X", "CT-001", trajectory, START, seed=seed, **kwargs
    )


def _values(observations, measurement_type):
    return [o.value for o in observations if o.measurement_type is measurement_type]


# -- determinism -----------------------------------------------------------


def test_same_seed_produces_identical_output():
    first = _generate(Trajectory.GRADUAL_DETERIORATION, seed=42)
    second = _generate(Trajectory.GRADUAL_DETERIORATION, seed=42)

    assert [o.model_dump() for o in first] == [o.model_dump() for o in second]


def test_different_seeds_produce_different_noise():
    first = _generate(Trajectory.STABLE, seed=1)
    second = _generate(Trajectory.STABLE, seed=2)

    assert [o.value for o in first] != [o.value for o in second]
    # But the same number of readings at the same timestamps.
    assert [o.recorded_at for o in first] == [o.recorded_at for o in second]


def test_observation_ids_are_stable_across_runs():
    """Ids must not come from uuid4, or replaying a scenario would not match."""
    first = _generate(seed=3)
    second = _generate(seed=3)

    assert [o.observation_id for o in first] == [o.observation_id for o in second]


# -- labelling -------------------------------------------------------------


def test_every_observation_is_labelled_synthetic():
    for observation in _generate(Trajectory.GRADUAL_DETERIORATION):
        assert observation.source is ObservationSource.SYNTHETIC
        assert observation.quality_note.startswith("synthetic:")


def test_generated_units_pass_ingestion_validation():
    """The generator must not emit rows its own pipeline would refuse."""
    for observation in _generate(Trajectory.STABLE):
        assert quality.check_observation(observation) is None


# -- longitudinal shape ----------------------------------------------------


def test_observations_are_ordered_and_span_the_window():
    observations = _generate(hours=4, interval_minutes=30)
    stamps = [o.recorded_at for o in observations]

    assert stamps == sorted(stamps)
    assert stamps[0] == START
    assert (stamps[-1] - stamps[0]).total_seconds() / 3600 == pytest.approx(4.0)


def test_deterioration_moves_vitals_in_the_expected_direction():
    """A trajectory, not independent draws: late readings differ from early ones."""
    observations = _generate(Trajectory.GRADUAL_DETERIORATION)

    heart_rate = _values(observations, MeasurementType.HEART_RATE)
    spo2 = _values(observations, MeasurementType.SPO2)

    assert heart_rate[-1] > heart_rate[0] + 30
    assert spo2[-1] < spo2[0] - 5


def test_recovery_moves_vitals_back_toward_normal():
    observations = _generate(Trajectory.RECOVERY)

    heart_rate = _values(observations, MeasurementType.HEART_RATE)
    spo2 = _values(observations, MeasurementType.SPO2)

    assert heart_rate[-1] < heart_rate[0] - 30
    assert spo2[-1] > spo2[0] + 5


def test_stable_trajectory_stays_near_baseline():
    heart_rate = _values(_generate(Trajectory.STABLE), MeasurementType.HEART_RATE)

    assert max(heart_rate) - min(heart_rate) < 10


def test_sudden_deterioration_holds_steady_then_breaks():
    observations = _generate(Trajectory.SUDDEN_DETERIORATION)
    heart_rate = _values(observations, MeasurementType.HEART_RATE)

    first_third = heart_rate[: len(heart_rate) // 3]
    assert max(first_third) - min(first_third) < 10
    assert heart_rate[-1] > heart_rate[0] + 30


# -- sensor failure --------------------------------------------------------


def test_noisy_sensor_drops_readings():
    noisy = _generate(Trajectory.NOISY_SENSOR)
    clean = _generate(Trajectory.STABLE)

    assert len(noisy) < len(clean)


def test_noisy_sensor_emits_rows_its_own_validator_refuses():
    """The demo needs a visible 'this row was rejected' moment."""
    rejected = [
        o for o in _generate(Trajectory.NOISY_SENSOR) if quality.check_observation(o)
    ]
    assert rejected


def test_noisy_sensor_loses_spo2_entirely_partway_through():
    """Drives the UNKNOWN path: a required measurement stops arriving."""
    observations = _generate(Trajectory.NOISY_SENSOR)

    spo2_times = [
        o.recorded_at for o in observations if o.measurement_type is MeasurementType.SPO2
    ]
    all_times = [o.recorded_at for o in observations]

    assert spo2_times, "SpO2 should be present at the start"
    assert max(spo2_times) < max(all_times), "SpO2 should stop before the run ends"


def test_gaps_are_never_back_filled():
    """An absent reading stays absent — no interpolation, no invention."""
    observations = _generate(Trajectory.NOISY_SENSOR)
    ids = [o.observation_id for o in observations]

    assert len(ids) == len(set(ids))


# -- windowing and cohort --------------------------------------------------


def test_windowed_preserves_every_observation():
    windows = generate_windowed("P-X", "CT-001", Trajectory.RECOVERY, START, windows=4, seed=7)
    flat = [o for window in windows for o in window]
    direct = _generate(Trajectory.RECOVERY, seed=7)

    assert len(flat) == len(direct)
    assert [o.observation_id for o in flat] == [o.observation_id for o in direct]


def test_windowed_returns_the_requested_number_of_batches():
    windows = generate_windowed("P-X", "CT-001", Trajectory.STABLE, START, windows=4, seed=7)
    assert len(windows) == 4
    assert all(window for window in windows)


def test_windows_are_chronologically_ordered():
    windows = generate_windowed("P-X", "CT-001", Trajectory.STABLE, START, windows=4, seed=7)

    latest = [max(o.recorded_at for o in window) for window in windows]
    assert latest == sorted(latest)


def test_cohort_covers_every_trajectory_and_is_reproducible():
    first = generate_cohort("CT-001", START, seed=11)
    second = generate_cohort("CT-001", START, seed=11)

    assert set(first) == {patient_id for patient_id, _ in COHORT}
    assert all(
        [o.model_dump() for o in first[pid]] == [o.model_dump() for o in second[pid]]
        for pid in first
    )


def test_cohort_patients_do_not_share_a_noise_sequence():
    cohort = generate_cohort("CT-001", START, seed=11)
    stable_a = _values(cohort["P-2001"], MeasurementType.HEART_RATE)
    stable_b = _values(cohort["P-2006"], MeasurementType.HEART_RATE)

    assert stable_a != stable_b
