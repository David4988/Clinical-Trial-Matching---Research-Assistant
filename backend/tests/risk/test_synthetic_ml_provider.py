"""The live ML risk provider."""

import builtins
from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring.state import build_patient_state
from app.risk.factory import build_risk_provider
from app.risk.synthetic_ml_provider import SyntheticMLProvider
from app.schema.monitoring import Observation
from app.schema.monitoring_enums import MeasurementType, ObservationSource, RiskLevel
from app.schema.monitoring_result import RiskAssessment
from app.synthetic.inference.engine import SyntheticInferenceEngine

M = MeasurementType
START = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)

UNITS = {
    M.HEART_RATE: "bpm",
    M.SPO2: "%",
    M.RESPIRATORY_RATE: "breaths/min",
    M.SYSTOLIC_BP: "mmHg",
}

#: (hr, spo2, rr, sbp) per five-minute window.
STEADY = ((70, 98, 15, 120), (71, 98, 15, 121), (70, 98, 15, 120))
DETERIORATING = ((70, 98, 15, 120), (72, 98, 15, 121), (88, 94, 21, 110))


@pytest.fixture(scope="module")
def provider():
    return SyntheticMLProvider()


def observations(patient_id, rows):
    return [
        Observation(
            observation_id=f"OBS-{patient_id}-{index}-{measurement.value}",
            patient_id=patient_id,
            trial_id="CT-TEST",
            recorded_at=START + timedelta(minutes=5 * index),
            source=ObservationSource.SYNTHETIC,
            measurement_type=measurement,
            value=value,
            unit=UNITS[measurement],
        )
        for index, row in enumerate(rows)
        for measurement, value in zip(
            (M.HEART_RATE, M.SPO2, M.RESPIRATORY_RATE, M.SYSTOLIC_BP), row
        )
    ]


def state_for(rows, patient_id="P-ML-1"):
    rows = tuple(rows)
    return build_patient_state(
        patient_id=patient_id,
        trial_id="CT-TEST",
        observations=observations(patient_id, rows),
        now=START + timedelta(minutes=5 * (len(rows) - 1)),
    )


def assess(provider, rows, patient_id="P-ML-1"):
    state = state_for(rows, patient_id)
    return provider.assess(state, state.as_of)


# -- the contract ----------------------------------------------------------


def test_returns_a_valid_risk_assessment(provider):
    risk = assess(provider, DETERIORATING)

    assert isinstance(risk, RiskAssessment)
    assert risk.patient_id == "P-ML-1"
    assert risk.trial_id == "CT-TEST"
    assert 0.0 <= risk.score <= 1.0
    assert 0.0 <= risk.confidence <= 1.0
    assert risk.level in set(RiskLevel)
    assert risk.assessment_id


def test_no_second_risk_schema_is_introduced(provider):
    risk = assess(provider, DETERIORATING)

    # The same field set every other provider returns, and still no action field.
    assert set(risk.model_dump()) == set(RiskAssessment.model_fields)
    assert not any(
        field in RiskAssessment.model_fields
        for field in ("intervention", "action", "recommendation", "next_dose")
    )


def test_no_sklearn_object_reaches_the_payload(provider):
    risk = assess(provider, DETERIORATING)

    dumped = risk.model_dump_json()
    assert "sklearn" not in dumped
    assert "IsolationForest" not in dumped or "ISOLATION_FOREST" in dumped


# -- provenance ------------------------------------------------------------


def test_provider_is_synthetic_ml_and_not_synthetic(provider):
    risk = assess(provider, DETERIORATING)

    assert risk.provider == "synthetic_ml"
    assert risk.provider != "synthetic"


def test_model_version_names_the_loaded_artifact(provider):
    risk = assess(provider, DETERIORATING)
    engine = SyntheticInferenceEngine()

    assert risk.model_version == engine.metadata["model_version"]
    assert any("synthetic_ml" in pattern for pattern in risk.likely_patterns)
    assert any(risk.model_version in pattern for pattern in risk.likely_patterns)


def test_feature_version_is_reported_alongside_the_model(provider):
    risk = assess(provider, DETERIORATING)

    assert any("Features:" in pattern for pattern in risk.likely_patterns)


# -- live input, not fixtures ----------------------------------------------


def test_the_verdict_follows_the_observations(provider):
    steady = assess(provider, STEADY)
    deteriorating = assess(provider, DETERIORATING)

    assert steady.level is RiskLevel.GREEN
    assert deteriorating.level is RiskLevel.RED
    assert deteriorating.score > steady.score


def test_the_patient_id_trajectory_label_is_ignored(provider):
    """The static provider keys off the id; this one must not.

    Identical physiology under two opposite scenario names has to produce one
    answer, or the model is not what is deciding.
    """
    named_stable = assess(provider, DETERIORATING, patient_id="PT-demo-STABLE")
    named_adverse = assess(provider, DETERIORATING, patient_id="PT-demo-ADVERSE_EVENT")

    assert named_stable.level == named_adverse.level
    assert named_stable.score == named_adverse.score


def test_the_static_demo_json_is_never_opened(provider, monkeypatch):
    opened: list[str] = []
    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recording_open)
    assess(provider, DETERIORATING)

    assert not any("synthetic_demo_cases" in path for path in opened)


def test_evidence_comes_from_the_live_window(provider):
    risk = assess(provider, DETERIORATING)
    factors = {f.factor: f for f in risk.contributing_factors}

    # HR 88, +16 since the previous window — the numbers that were measured.
    assert "88" in factors["HEART_RATE"].detail
    assert "+16" in factors["HEART_RATE"].detail
    assert "94" in factors["SPO2"].detail
    assert "-4" in factors["SPO2"].detail
    assert factors["ISOLATION_FOREST"].detail


def test_contributing_factor_weights_stay_in_range(provider):
    risk = assess(provider, DETERIORATING)

    assert risk.contributing_factors
    assert all(0.0 <= f.weight <= 1.0 for f in risk.contributing_factors)


# -- determinism -----------------------------------------------------------


def test_the_same_state_produces_the_same_assessment(provider):
    results = [assess(provider, DETERIORATING) for _ in range(5)]

    assert len({r.score for r in results}) == 1
    assert len({r.level for r in results}) == 1


# -- degrading -------------------------------------------------------------


def test_first_window_is_unknown_but_not_a_provider_failure(provider):
    risk = assess(provider, DETERIORATING[:1])

    assert risk.level is RiskLevel.UNKNOWN
    assert risk.score == 0.0
    # The provider worked; the record simply cannot support a verdict yet.
    assert risk.degraded is False
    assert any("invented" in pattern for pattern in risk.likely_patterns)


def test_a_missing_artifact_degrades_instead_of_raising(tmp_path):
    broken = SyntheticMLProvider(engine=SyntheticInferenceEngine(tmp_path))
    risk = assess(broken, DETERIORATING)

    assert risk.degraded is True
    assert risk.level is RiskLevel.UNKNOWN
    assert risk.provider == "synthetic_ml"


def test_assess_never_raises_even_on_a_broken_engine(provider, monkeypatch):
    class Exploding:
        model_version = "x"
        feature_version = "y"

        def score(self, _state):
            raise RuntimeError("boom")

    monkeypatch.setattr(provider, "_engine", Exploding())
    risk = assess(provider, DETERIORATING)

    assert risk.degraded is True
    assert risk.level is RiskLevel.UNKNOWN


# -- the optional narration layer ------------------------------------------


def test_a_narrator_can_only_add_prose(provider):
    seen = {}

    def narrator(evidence, explanation):
        seen["evidence"] = evidence
        seen["explanation"] = explanation
        return ["A clinician-facing sentence."]

    with_narration = SyntheticMLProvider(
        engine=provider._engine, narrator=narrator  # noqa: SLF001
    )
    plain = assess(provider, DETERIORATING)
    narrated = assess(with_narration, DETERIORATING)

    assert "A clinician-facing sentence." in narrated.likely_patterns
    # The score, level and evidence are identical with and without it.
    assert narrated.score == plain.score
    assert narrated.level == plain.level
    assert [f.detail for f in narrated.contributing_factors] == [
        f.detail for f in plain.contributing_factors
    ]
    # It was handed the finished evidence, and produced none of it.
    assert seen["evidence"]["anomaly_score"] == pytest.approx(
        seen["explanation"]["anomaly_score"]
    )


def test_a_failing_narrator_does_not_break_the_cycle(provider):
    def narrator(_evidence, _explanation):
        raise RuntimeError("the LLM is down")

    risk = assess(
        SyntheticMLProvider(engine=provider._engine, narrator=narrator),  # noqa: SLF001
        DETERIORATING,
    )

    assert risk.degraded is False
    assert risk.level is RiskLevel.RED


# -- the factory -----------------------------------------------------------


def test_factory_builds_each_provider_by_name():
    assert build_risk_provider("mock").name == "mock-risk-v1"
    assert build_risk_provider("synthetic").name == "synthetic"
    assert build_risk_provider("synthetic_ml").name == "synthetic_ml"


def test_factory_falls_back_to_the_mock_for_an_unknown_name():
    assert build_risk_provider("nonsense").name == "mock-risk-v1"


def test_factory_reads_the_environment(monkeypatch):
    monkeypatch.setenv("RISK_PROVIDER", "synthetic_ml")
    assert build_risk_provider().name == "synthetic_ml"
