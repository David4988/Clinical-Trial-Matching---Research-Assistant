"""The model artifact and the inference engine that loads it."""

import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from app.schema.monitoring import Observation
from app.schema.monitoring_enums import MeasurementType, ObservationSource
from app.synthetic.inference.contract import (
    EXPECTED_FEATURE_VERSION,
    EXPECTED_MODEL_VERSION,
    FEATURE_ORDER,
    ModelUnavailable,
)
from app.synthetic.inference.engine import (
    ARTIFACT_DIR,
    METADATA_PATH,
    MODEL_PATH,
    SyntheticInferenceEngine,
)
from app.synthetic.inference.windows import PatientWindowState

M = MeasurementType
START = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)
UNITS = {M.HEART_RATE: "bpm", M.SPO2: "%", M.RESPIRATORY_RATE: "breaths/min"}


@pytest.fixture(scope="module")
def engine():
    return SyntheticInferenceEngine()


def state_for(previous, current, patient_id="P1"):
    """A two-window patient record from two (hr, spo2, rr) triples."""
    observations = [
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
        for index, row in enumerate((previous, current))
        for measurement, value in zip(
            (M.HEART_RATE, M.SPO2, M.RESPIRATORY_RATE), row
        )
    ]
    return PatientWindowState.from_observations(patient_id, observations)


# -- the artifact ----------------------------------------------------------


def test_training_produced_a_model_file():
    assert MODEL_PATH.exists(), "run train_model_artifact.py and copy the pair across"
    assert MODEL_PATH.stat().st_size > 0


def test_metadata_file_exists_beside_it():
    assert METADATA_PATH.exists()
    assert json.loads(METADATA_PATH.read_text())


def test_metadata_matches_the_frozen_configuration():
    metadata = json.loads(METADATA_PATH.read_text())

    assert metadata["model_version"] == EXPECTED_MODEL_VERSION
    assert metadata["feature_version"] == EXPECTED_FEATURE_VERSION
    assert tuple(metadata["features"]["names"]) == FEATURE_ORDER
    assert metadata["features"]["preprocessing"] == "none"

    estimator = metadata["estimator"]
    assert estimator["class"] == "sklearn.ensemble.IsolationForest"
    assert estimator["contamination"] == 0.10
    assert estimator["random_state"] == 42
    assert estimator["n_estimators"] == 100

    cohort = metadata["training_cohort"]
    assert sorted(cohort["scenarios"]) == ["IMPROVING", "STABLE"]
    assert cohort["random_seed"] == 42
    assert cohort["evaluation_half_used_in_fit"] is False


def test_metadata_matches_the_loaded_estimator(engine):
    metadata = engine.metadata
    model = engine._model  # noqa: SLF001 - asserting the artifact, not the API

    assert model.contamination == metadata["estimator"]["contamination"]
    assert model.random_state == metadata["estimator"]["random_state"]
    assert model.n_estimators == metadata["estimator"]["n_estimators"]
    assert model.offset_ == pytest.approx(metadata["estimator"]["offset_"])
    assert model.n_features_in_ == len(FEATURE_ORDER)


def test_model_reloads_from_disk_into_a_fresh_engine():
    first = SyntheticInferenceEngine().score(state_for((70, 98, 15), (88, 94, 21)))
    second = SyntheticInferenceEngine().score(state_for((70, 98, 15), (88, 94, 21)))

    assert first.scored and second.scored
    assert first.anomaly_score == second.anomaly_score
    assert first.predicted_anomaly == second.predicted_anomaly


# -- refusing a bad artifact -----------------------------------------------


def test_missing_artifact_raises_model_unavailable(tmp_path):
    with pytest.raises(ModelUnavailable, match="incomplete"):
        SyntheticInferenceEngine(tmp_path).metadata


def test_reordered_features_are_refused_rather_than_scored(tmp_path):
    shutil.copy(MODEL_PATH, tmp_path / MODEL_PATH.name)
    metadata = json.loads(METADATA_PATH.read_text())
    metadata["features"]["names"] = list(reversed(FEATURE_ORDER))
    (tmp_path / METADATA_PATH.name).write_text(json.dumps(metadata))

    # A permuted vector would score without raising, so this must be caught here.
    with pytest.raises(ModelUnavailable, match="feature order"):
        SyntheticInferenceEngine(tmp_path).metadata


def test_checksum_mismatch_is_refused(tmp_path):
    shutil.copy(MODEL_PATH, tmp_path / MODEL_PATH.name)
    metadata = json.loads(METADATA_PATH.read_text())
    metadata["model_sha256"] = "0" * 64
    (tmp_path / METADATA_PATH.name).write_text(json.dumps(metadata))

    with pytest.raises(ModelUnavailable, match="checksum"):
        SyntheticInferenceEngine(tmp_path).metadata


# -- inference -------------------------------------------------------------


def test_known_normal_sample_is_not_flagged(engine):
    # Steady vitals, negligible movement: the shape the cohort was fitted on.
    result = engine.score(state_for((70, 98, 15), (71, 98, 15)))

    assert result.scored
    assert result.predicted_anomaly == 0
    assert result.anomaly_score < 0


def test_known_sudden_change_sample_is_flagged(engine):
    result = engine.score(state_for((70, 98, 15), (88, 94, 21)))

    assert result.scored
    assert result.predicted_anomaly == 1
    assert result.anomaly_score > 0


def test_known_adverse_event_like_sample_is_flagged(engine):
    # The research ADVERSE_SHIFT: HR +30, SpO2 -8, RR +10.
    result = engine.score(state_for((72, 97, 16), (102, 89, 26)))

    assert result.scored
    assert result.predicted_anomaly == 1


def test_a_larger_excursion_scores_higher(engine):
    mild = engine.score(state_for((70, 98, 15), (76, 97, 17)))
    severe = engine.score(state_for((70, 98, 15), (110, 88, 28)))

    assert severe.anomaly_score > mild.anomaly_score


def test_repeated_inference_is_deterministic(engine):
    state = state_for((70, 98, 15), (88, 94, 21))
    scores = {engine.score(state).anomaly_score for _ in range(10)}

    assert len(scores) == 1


def test_result_reports_the_exact_vector_that_entered_the_model(engine):
    result = engine.score(state_for((70, 98, 15), (88, 94, 21)))

    assert list(result.feature_values) == list(FEATURE_ORDER)
    assert result.feature_values == {
        "heart_rate": 88.0,
        "spo2": 94.0,
        "respiratory_rate": 21.0,
        "heart_rate_delta": 18.0,
        "spo2_delta": -4.0,
        "respiratory_rate_delta": 6.0,
    }


def test_unscoreable_window_returns_a_reason_and_no_score(engine):
    single = state_for((70, 98, 15), (88, 94, 21))
    first_only = PatientWindowState(patient_id="P1", current=single.current)

    result = engine.score(first_only)

    assert result.scored is False
    assert result.anomaly_score is None
    assert result.predicted_anomaly is None
    assert result.reason


def test_provenance_travels_with_every_result(engine):
    result = engine.score(state_for((70, 98, 15), (88, 94, 21)))

    assert result.model_version == EXPECTED_MODEL_VERSION
    assert result.feature_version == EXPECTED_FEATURE_VERSION


def test_scoring_does_not_mutate_the_estimator(engine):
    model = engine._model  # noqa: SLF001
    before = (model.offset_, model.n_estimators, model.contamination)

    engine.score(state_for((70, 98, 15), (140, 80, 35)))

    assert (model.offset_, model.n_estimators, model.contamination) == before


def test_artifacts_live_beside_the_static_demo_fixture():
    # Both synthetic paths ship together; neither replaces the other.
    assert (ARTIFACT_DIR / "synthetic_demo_cases.json").exists()
    assert MODEL_PATH.exists()
