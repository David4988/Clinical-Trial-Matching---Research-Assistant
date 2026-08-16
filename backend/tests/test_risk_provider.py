"""M6: the risk provider boundary and the deterministic mock.

The headline test is `test_deteriorating_trajectory_escalates_green_amber_red`
and its recovery counterpart: they prove the demo's central claim, and they
prove it by feeding real synthetic trajectories through the real state engine
rather than by asserting against a scripted sequence.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring import protocol, quality
from app.monitoring.state import build_patient_state
from app.risk.mock_provider import MockRiskProvider
from app.risk.provider import RiskProvider
from app.schema.monitoring import AdverseEvent, Observation
from app.schema.monitoring_enums import (
    AdverseEventSeverity,
    MeasurementType,
    ObservationSource,
    RiskLevel,
)
from app.schema.monitoring_result import PatientState
from app.synthetic.generator import Trajectory, generate_windowed

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
START = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)

M = MeasurementType


@pytest.fixture
def provider() -> MockRiskProvider:
    return MockRiskProvider()


def _obs(measurement_type, value, unit, minutes_ago, index=0) -> Observation:
    return Observation(
        observation_id=f"OBS-{measurement_type.value}-{minutes_ago}-{index}",
        patient_id="P-1042",
        trial_id="CT-001",
        recorded_at=NOW - timedelta(minutes=minutes_ago),
        source=ObservationSource.SYNTHETIC,
        measurement_type=measurement_type,
        value=value,
        unit=unit,
    )


def _vitals(hr, sbp, spo2, temp=36.8, rr=14.0, samples=4) -> list[Observation]:
    """A flat record sitting at the given values."""
    rows: list[Observation] = []
    for i in range(samples):
        minutes = (samples - 1 - i) * 10
        rows.extend(
            [
                _obs(M.HEART_RATE, hr, "bpm", minutes, i),
                _obs(M.SYSTOLIC_BP, sbp, "mmHg", minutes, i),
                _obs(M.SPO2, spo2, "%", minutes, i),
                _obs(M.TEMPERATURE, temp, "C", minutes, i),
                _obs(M.RESPIRATORY_RATE, rr, "breaths/min", minutes, i),
            ]
        )
    return rows


def _state(observations, adverse_events=None) -> PatientState:
    return build_patient_state(
        "P-1042", "CT-001", observations, NOW, adverse_events=adverse_events
    )


def _run_trajectory(trajectory: Trajectory, provider, windows=5, seed=7):
    """Ingest a trajectory window by window, returning the level after each."""
    batches = generate_windowed(
        "P-X", "CT-001", trajectory, START, windows=windows, hours=8, seed=seed
    )
    accumulated: list[Observation] = []
    levels: list[RiskLevel] = []

    for batch in batches:
        # The real path: invalid rows never reach the store.
        accumulated.extend(o for o in batch if quality.check_observation(o) is None)
        now = max(o.recorded_at for o in accumulated)
        state = build_patient_state("P-X", "CT-001", accumulated, now)
        levels.append(provider.assess(state, now).level)

    return levels


def _collapse(levels):
    """Drop consecutive duplicates: GREEN,GREEN,AMBER -> GREEN,AMBER."""
    collapsed = []
    for level in levels:
        if not collapsed or collapsed[-1] is not level:
            collapsed.append(level)
    return collapsed


# -- the boundary ----------------------------------------------------------


def test_mock_implements_the_provider_interface(provider):
    assert isinstance(provider, RiskProvider)


def test_assessment_carries_provider_identity(provider):
    assessment = provider.assess(_state(_vitals(72, 120, 98)), NOW)

    assert assessment.provider == "mock-risk-v1"
    assert assessment.model_version == "0.1.0"
    assert assessment.prediction_horizon_hours == protocol.PREDICTION_HORIZON_HOURS


def test_provider_is_deterministic(provider):
    observations = _vitals(112, 94, 92.5)

    first = provider.assess(_state(observations), NOW)
    second = provider.assess(_state(observations), NOW)

    assert first.level is second.level
    assert first.score == second.score
    assert first.confidence == second.confidence


def test_provider_does_not_mutate_the_state(provider):
    state = _state(_vitals(72, 120, 98))
    before = state.model_dump()

    provider.assess(state, NOW)

    assert state.model_dump() == before


def test_provider_never_raises(provider):
    """A broken provider must degrade, not abort the monitoring cycle."""

    class Exploding(MockRiskProvider):
        def _assess(self, state, now):
            raise RuntimeError("model unavailable")

    assessment = Exploding().assess(_state(_vitals(72, 120, 98)), NOW)

    assert assessment.degraded is True
    assert assessment.level is RiskLevel.UNKNOWN
    assert assessment.confidence == 0.0


# -- banding ---------------------------------------------------------------


def test_healthy_vitals_are_green(provider):
    assessment = provider.assess(_state(_vitals(72, 120, 98)), NOW)

    assert assessment.level is RiskLevel.GREEN
    assert assessment.score < protocol.GREEN_BELOW


def test_mildly_abnormal_vitals_are_amber(provider):
    assessment = provider.assess(_state(_vitals(112, 94, 92.5, 38.0, 24.0)), NOW)

    assert assessment.level is RiskLevel.AMBER


def test_severely_abnormal_vitals_are_red(provider):
    assessment = provider.assess(_state(_vitals(142, 88, 86, 39.0, 31.0)), NOW)

    assert assessment.level is RiskLevel.RED
    assert assessment.score >= protocol.AMBER_BELOW


def test_no_measurements_is_unknown_not_green(provider):
    """Absence of evidence is never read as evidence of safety."""
    assessment = provider.assess(_state([]), NOW)

    assert assessment.level is RiskLevel.UNKNOWN
    assert assessment.confidence == 0.0


# -- explainability --------------------------------------------------------


def test_contributing_factors_name_the_offending_measurements(provider):
    assessment = provider.assess(_state(_vitals(142, 88, 86, 39.0, 31.0)), NOW)

    named = {f.measurement_type for f in assessment.contributing_factors}
    assert M.SPO2 in named
    assert M.HEART_RATE in named
    assert all(f.detail for f in assessment.contributing_factors)


def test_contributing_factors_are_worst_first(provider):
    assessment = provider.assess(_state(_vitals(142, 88, 86, 39.0, 31.0)), NOW)
    weights = [f.weight for f in assessment.contributing_factors]

    assert weights == sorted(weights, reverse=True)


def test_healthy_patient_has_no_contributing_factors(provider):
    assessment = provider.assess(_state(_vitals(72, 120, 98)), NOW)
    assert assessment.contributing_factors == []


def test_patterns_describe_multi_measurement_shapes(provider):
    """Rising heart rate with falling saturation is a recognised shape."""
    observations: list[Observation] = []
    for i, (hr, spo2) in enumerate([(72, 98), (90, 95), (110, 92), (130, 88)]):
        minutes = (3 - i) * 20
        observations.extend(
            [
                _obs(M.HEART_RATE, hr, "bpm", minutes, i),
                _obs(M.SPO2, spo2, "%", minutes, i),
                _obs(M.SYSTOLIC_BP, 120, "mmHg", minutes, i),
            ]
        )

    assessment = provider.assess(_state(observations), NOW)

    assert any("saturation" in p for p in assessment.likely_patterns)


# -- trends and adverse events --------------------------------------------


def test_a_climbing_value_scores_above_the_same_value_holding_steady(provider):
    """Trend is part of the picture, not just the current number."""
    steady = _vitals(112, 120, 98)
    climbing: list[Observation] = []
    for i, hr in enumerate([95, 101, 107, 112]):
        minutes = (3 - i) * 20
        climbing.extend(
            [
                _obs(M.HEART_RATE, hr, "bpm", minutes, i),
                _obs(M.SYSTOLIC_BP, 120, "mmHg", minutes, i),
                _obs(M.SPO2, 98, "%", minutes, i),
            ]
        )

    steady_score = provider.assess(_state(steady), NOW).score
    climbing_score = provider.assess(_state(climbing), NOW).score

    assert climbing_score > steady_score


def test_active_adverse_events_add_to_risk(provider):
    observations = _vitals(104, 118, 95)
    event = AdverseEvent(
        event_id="AE-1",
        patient_id="P-1042",
        trial_id="CT-001",
        term="Dyspnoea",
        severity=AdverseEventSeverity.SEVERE,
        onset_at=NOW,
    )

    without = provider.assess(_state(observations), NOW).score
    with_event = provider.assess(_state(observations, [event]), NOW).score

    assert with_event > without


def test_confidence_is_independent_of_score(provider):
    """Being worried and being certain are different things."""
    thin = provider.assess(_state(_vitals(142, 88, 86, samples=3)), NOW)
    deep = provider.assess(_state(_vitals(142, 88, 86, samples=10)), NOW)

    assert thin.level is deep.level
    assert deep.confidence > thin.confidence


def test_incomplete_records_lower_confidence(provider):
    complete = _vitals(72, 120, 98)
    partial = [o for o in complete if o.measurement_type is not M.SPO2]

    assert (
        provider.assess(_state(partial), NOW).confidence
        < provider.assess(_state(complete), NOW).confidence
    )


# -- the demo claim --------------------------------------------------------


def test_deteriorating_trajectory_escalates_green_amber_red(provider):
    """THE demo claim, proven against generated data rather than a script."""
    levels = _collapse(_run_trajectory(Trajectory.GRADUAL_DETERIORATION, provider))

    assert levels == [RiskLevel.GREEN, RiskLevel.AMBER, RiskLevel.RED]


def test_sudden_deterioration_also_passes_through_amber(provider):
    levels = _collapse(_run_trajectory(Trajectory.SUDDEN_DETERIORATION, provider))

    assert levels == [RiskLevel.GREEN, RiskLevel.AMBER, RiskLevel.RED]


def test_recovering_trajectory_de_escalates_red_amber_green(provider):
    levels = _collapse(_run_trajectory(Trajectory.RECOVERY, provider))

    assert levels == [RiskLevel.RED, RiskLevel.AMBER, RiskLevel.GREEN]


def test_stable_trajectory_stays_green(provider):
    levels = _run_trajectory(Trajectory.STABLE, provider)

    assert set(levels) == {RiskLevel.GREEN}


def test_improving_trajectory_settles_to_green(provider):
    levels = _run_trajectory(Trajectory.IMPROVING, provider)

    assert levels[0] is RiskLevel.AMBER
    assert levels[-1] is RiskLevel.GREEN


def test_transitions_are_reproducible_for_a_fixed_seed(provider):
    first = _run_trajectory(Trajectory.GRADUAL_DETERIORATION, provider, seed=99)
    second = _run_trajectory(Trajectory.GRADUAL_DETERIORATION, provider, seed=99)

    assert first == second
