"""Temporal state and feature extraction for live inference."""

from datetime import datetime, timedelta, timezone

import pytest

from app.schema.monitoring import Observation
from app.schema.monitoring_enums import MeasurementType, ObservationSource
from app.synthetic.inference.contract import FEATURE_ORDER
from app.synthetic.inference.windows import PatientWindowState, build_windows

M = MeasurementType
START = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)

UNITS = {
    M.HEART_RATE: "bpm",
    M.SPO2: "%",
    M.RESPIRATORY_RATE: "breaths/min",
    M.SYSTOLIC_BP: "mmHg",
}


def window(patient_id, minute, hr=None, spo2=None, rr=None, sbp=None):
    """Observations for one instant. A None signal is simply not recorded."""
    at = START + timedelta(minutes=minute)
    values = {M.HEART_RATE: hr, M.SPO2: spo2, M.RESPIRATORY_RATE: rr, M.SYSTOLIC_BP: sbp}
    return [
        Observation(
            observation_id=f"OBS-{patient_id}-{minute}-{measurement.value}",
            patient_id=patient_id,
            trial_id="CT-TEST",
            recorded_at=at,
            source=ObservationSource.SYNTHETIC,
            measurement_type=measurement,
            value=value,
            unit=UNITS[measurement],
        )
        for measurement, value in values.items()
        if value is not None
    ]


# -- feature ordering ------------------------------------------------------


def test_feature_order_is_the_frozen_contract():
    assert FEATURE_ORDER == (
        "heart_rate",
        "spo2",
        "respiratory_rate",
        "heart_rate_delta",
        "spo2_delta",
        "respiratory_rate_delta",
    )


def test_features_are_positional_and_follow_the_contract_order():
    observations = window("P1", 0, 70, 98, 15) + window("P1", 5, 88, 94, 21)
    features = PatientWindowState.from_observations("P1", observations).features()

    assert features == (88.0, 94.0, 21.0, 18.0, -4.0, 6.0)
    # Values, then deltas — never interleaved, never alphabetical.
    assert dict(zip(FEATURE_ORDER, features))["spo2_delta"] == -4.0


# -- delta calculation -----------------------------------------------------


def test_delta_is_current_minus_previous():
    observations = window("P1", 0, 70.5, 98.0, 15.0) + window("P1", 5, 72.5, 97.0, 16.5)
    features = PatientWindowState.from_observations("P1", observations).features()

    assert features[3] == pytest.approx(2.0)
    assert features[4] == pytest.approx(-1.0)
    assert features[5] == pytest.approx(1.5)


def test_delta_uses_the_immediately_preceding_window_not_the_first():
    observations = (
        window("P1", 0, 60, 99, 12)
        + window("P1", 5, 70, 98, 15)
        + window("P1", 10, 72, 97, 16)
    )
    features = PatientWindowState.from_observations("P1", observations).features()

    assert features[:3] == (72.0, 97.0, 16.0)
    assert features[3] == pytest.approx(2.0)  # against t=5, not t=0


def test_delta_is_rounded_to_four_decimals_like_research():
    observations = window("P1", 0, 70.0, 98.0, 15.0) + window(
        "P1", 5, 70.123456, 98.0, 15.0
    )
    features = PatientWindowState.from_observations("P1", observations).features()

    assert features[3] == 0.1235


# -- first window ----------------------------------------------------------


def test_first_window_has_no_features_and_nothing_is_fabricated():
    state = PatientWindowState.from_observations("P1", window("P1", 0, 70, 98, 15))

    assert state.current is not None
    assert state.previous is None
    assert state.features() is None
    assert "invented" in state.unscoreable_reason()


def test_no_complete_window_at_all_is_reported_separately():
    # Respiratory rate never arrives, so no instant is a complete window.
    state = PatientWindowState.from_observations("P1", window("P1", 0, 70, 98, None))

    assert state.current is None
    assert state.features() is None
    assert "same instant" in state.unscoreable_reason()


def test_incomplete_predecessor_is_not_filled_in():
    # t=0 is missing SpO2, so it is not a window and t=5 has no predecessor.
    observations = window("P1", 0, 70, None, 15) + window("P1", 5, 88, 94, 21)
    state = PatientWindowState.from_observations("P1", observations)

    assert state.previous is None
    assert state.features() is None


# -- patient boundaries ----------------------------------------------------


def test_windows_are_scoped_to_one_patient():
    observations = (
        window("P1", 0, 70, 98, 15)
        + window("P2", 0, 140, 88, 30)
        + window("P1", 5, 72, 98, 15)
        + window("P2", 5, 145, 86, 32)
    )

    p1 = PatientWindowState.from_observations("P1", observations)
    p2 = PatientWindowState.from_observations("P2", observations)

    assert p1.features()[:3] == (72.0, 98.0, 15.0)
    assert p2.features()[:3] == (145.0, 86.0, 32.0)
    # P1's delta must not have been taken against P2's reading.
    assert p1.features()[3] == pytest.approx(2.0)
    assert p2.features()[3] == pytest.approx(5.0)


def test_a_second_patients_history_cannot_supply_a_missing_predecessor():
    # P2 has one window; P1 has two. P2 must stay unscoreable.
    observations = (
        window("P1", 0, 70, 98, 15)
        + window("P1", 5, 72, 98, 15)
        + window("P2", 5, 140, 88, 30)
    )
    assert PatientWindowState.from_observations("P2", observations).features() is None


# -- window construction ---------------------------------------------------


def test_windows_are_ordered_oldest_first_regardless_of_input_order():
    observations = window("P1", 10, 72, 97, 16) + window("P1", 0, 70, 98, 15)
    windows = build_windows("P1", observations)

    assert [w.recorded_at for w in windows] == sorted(w.recorded_at for w in windows)
    assert windows[0].value("heart_rate") == 70.0


def test_later_reading_wins_when_a_signal_repeats_at_one_instant():
    observations = window("P1", 0, 70, 98, 15) + window("P1", 0, 75, 98, 15)
    windows = build_windows("P1", observations)

    assert len(windows) == 1
    assert windows[0].value("heart_rate") == 75.0


def test_non_model_measurements_are_ignored_but_do_not_break_a_window():
    observations = window("P1", 0, 70, 98, 15, sbp=120) + window(
        "P1", 5, 72, 98, 15, sbp=180
    )
    features = PatientWindowState.from_observations("P1", observations).features()

    # Systolic BP swung 60 mmHg and changed nothing: it is not a model feature.
    assert features == (72.0, 98.0, 15.0, 2.0, 0.0, 0.0)


def test_state_advances_as_new_windows_arrive():
    history = window("P1", 0, 70, 98, 15)
    first = PatientWindowState.from_observations("P1", history)
    assert first.previous is None

    history += window("P1", 5, 72, 98, 15)
    second = PatientWindowState.from_observations("P1", history)
    assert second.previous.value("heart_rate") == 70.0
    assert second.current.value("heart_rate") == 72.0

    history += window("P1", 10, 88, 94, 21)
    third = PatientWindowState.from_observations("P1", history)
    assert third.previous.value("heart_rate") == 72.0
    assert third.current.value("heart_rate") == 88.0
    assert third.current.recorded_at > third.previous.recorded_at
