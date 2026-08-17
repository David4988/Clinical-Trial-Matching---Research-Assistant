"""Application inference must agree with the research pipeline.

This is the integration test that matters. The two repositories build the same
six features by different code, from different inputs — research from a pandas
`groupby().shift(1)` over a CSV, the application from `Observation` rows grouped
by timestamp — and then score them with the same serialised estimator.

If those two paths ever disagree, every published research metric stops
describing what the application actually does. So the fixture is not a set of
handpicked easy cases: it is every scenario in the generator, balanced between
flagged and unflagged windows, all drawn from the evaluation half of the patient
split, and all compared feature by feature.

Regenerate the fixture in the research repository with:

    .venv/bin/python export_inference_fixtures.py
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.schema.monitoring import Observation
from app.schema.monitoring_enums import MeasurementType, ObservationSource
from app.synthetic.inference.contract import FEATURE_ORDER
from app.synthetic.inference.engine import SyntheticInferenceEngine
from app.synthetic.inference.windows import PatientWindowState

FIXTURE = Path(__file__).parent / "fixtures" / "research_inference_parity.json"

M = MeasurementType
START = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
UNITS = {M.HEART_RATE: "bpm", M.SPO2: "%", M.RESPIRATORY_RATE: "breaths/min"}

#: Features are compared exactly. They are built by arithmetic on the same
#: decimals in both repositories, so anything but equality is a real defect.
FEATURE_TOLERANCE = 0.0

#: Scores are compared within float noise. The two runtimes differ (research
#: fits under Python 3.14 / numpy 2.5, the application scores under 3.11 /
#: numpy 2.4), so the tolerance covers cross-version float summation order in
#: `decision_function` and nothing larger.
SCORE_TOLERANCE = 1e-9


def _load():
    if not FIXTURE.exists():  # pragma: no cover - fixture ships with the repo
        pytest.skip(f"Parity fixture missing: {FIXTURE}")
    return json.loads(FIXTURE.read_text())


PAYLOAD = _load()
CASES = PAYLOAD["cases"]


@pytest.fixture(scope="module")
def engine():
    return SyntheticInferenceEngine()


def _observations(case):
    """Rebuild the two windows as ordinary application observations."""
    patient_id = case["patient_id"]
    minutes = PAYLOAD["window_minutes"]
    return [
        Observation(
            observation_id=f"OBS-{patient_id}-{index}-{measurement.value}",
            patient_id=patient_id,
            trial_id="TRIAL-001",
            recorded_at=START + timedelta(minutes=minutes * index),
            source=ObservationSource.SYNTHETIC,
            measurement_type=measurement,
            value=row[signal],
            unit=UNITS[measurement],
        )
        for index, row in enumerate((case["previous"], case["current"]))
        for measurement, signal in (
            (M.HEART_RATE, "heart_rate"),
            (M.SPO2, "spo2"),
            (M.RESPIRATORY_RATE, "respiratory_rate"),
        )
    ]


def _ids(case):
    return f"{case['scenario']}-{case['patient_id']}-w{case['window_index']}"


# -- the fixture describes the artifact this build loads -------------------


def test_fixture_and_application_agree_on_the_contract(engine):
    assert tuple(PAYLOAD["feature_order"]) == FEATURE_ORDER
    assert PAYLOAD["model_version"] == engine.metadata["model_version"]
    assert PAYLOAD["feature_version"] == engine.metadata["feature_version"]
    # Same bytes: the application is scoring with the file research exported from.
    assert PAYLOAD["model_sha256"] == engine.metadata["model_sha256"]


def test_fixture_covers_every_scenario_and_both_labels():
    scenarios = {case["scenario"] for case in CASES}
    assert scenarios == {
        "STABLE",
        "IMPROVING",
        "GRADUAL_DETERIORATION",
        "SUDDEN_DETERIORATION",
        "RECOVERY",
        "ADVERSE_EVENT",
        "DATA_QUALITY_FAILURE",
    }
    labels = {case["expected_predicted_anomaly"] for case in CASES}
    assert labels == {0, 1}


# -- feature vectors -------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_feature_vector_matches_research_exactly(case):
    state = PatientWindowState.from_observations(
        case["patient_id"], _observations(case)
    )
    features = state.features()

    assert features is not None, "the application failed to build a vector at all"
    expected = tuple(case["expected_features"][name] for name in FEATURE_ORDER)

    assert features == pytest.approx(expected, abs=FEATURE_TOLERANCE), (
        f"feature mismatch for {_ids(case)}: "
        f"app={dict(zip(FEATURE_ORDER, features))} research={case['expected_features']}"
    )


# -- scores and labels -----------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_anomaly_score_matches_research(case, engine):
    state = PatientWindowState.from_observations(
        case["patient_id"], _observations(case)
    )
    result = engine.score(state)

    assert result.scored
    assert result.anomaly_score == pytest.approx(
        case["expected_anomaly_score"], abs=SCORE_TOLERANCE
    )


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_predicted_label_matches_research(case, engine):
    state = PatientWindowState.from_observations(
        case["patient_id"], _observations(case)
    )
    result = engine.score(state)

    assert result.predicted_anomaly == case["expected_predicted_anomaly"]


def test_every_case_agrees_and_the_worst_drift_is_reported(engine):
    """One aggregate assertion, so a partial disagreement cannot look like noise."""
    drifts = []
    label_mismatches = []

    for case in CASES:
        state = PatientWindowState.from_observations(
            case["patient_id"], _observations(case)
        )
        result = engine.score(state)
        drifts.append(abs(result.anomaly_score - case["expected_anomaly_score"]))
        if result.predicted_anomaly != case["expected_predicted_anomaly"]:
            label_mismatches.append(_ids(case))

    assert not label_mismatches, f"labels disagree on: {label_mismatches}"
    assert max(drifts) <= SCORE_TOLERANCE, (
        f"worst score drift {max(drifts):.3e} across {len(CASES)} windows "
        f"exceeds {SCORE_TOLERANCE:.0e}"
    )
