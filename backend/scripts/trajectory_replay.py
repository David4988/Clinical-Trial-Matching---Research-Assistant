"""Replay a synthetic patient trajectory through the real application.

Shared by `live_trajectory_demo.py` and `tests/test_live_trajectory_e2e.py`, so
the demo and the test exercise one code path rather than two that can drift.

Every window goes in through the ordinary HTTP endpoints:

    POST /monitoring/observations            ingest the window
    POST /monitoring/patients/{id}/cycle     state -> risk -> gate -> protocol

Nothing here calls the model, the provider, or `build_patient_state` to drive
the flow. The application is a black box during replay.

Reading the six features and the raw anomaly score back out
-----------------------------------------------------------
`RiskAssessment` deliberately exposes a banded level and a [0, 1] display score,
not the estimator's native output — and the production API is not going to grow
a debug field to make a demo prettier. So after each window the harness fetches
the patient's observations *back through the API* and recomputes the feature
vector and score with the same inference components the provider used.

That recomputation is then tied to reality rather than trusted: the harness
asserts the level and display score it derives equal the ones the cycle response
actually returned. If the provider had scored something else, the check fails.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import create_app  # noqa: E402
from app.monitoring.context import MonitoringContext  # noqa: E402
from app.repository.json_monitoring import JsonMonitoringRepository  # noqa: E402
from app.repository.json_repo import JsonRepository  # noqa: E402
from app.risk.factory import build_risk_provider  # noqa: E402
from app.risk.synthetic_ml_provider import _display_score, _level_for  # noqa: E402
from app.schema.monitoring_enums import MeasurementType  # noqa: E402
from app.service import ScreeningService  # noqa: E402
from app.synthetic.inference.contract import FEATURE_ORDER  # noqa: E402,F401
from app.synthetic.inference.engine import default_engine  # noqa: E402
from app.synthetic.inference.windows import PatientWindowState  # noqa: E402

TRAJECTORY_FIXTURE = BACKEND_ROOT / "tests" / "fixtures" / "research_trajectory.json"

DEFAULT_PATIENT = "PT-DEMO-001"
DEFAULT_TRIAL = "CT-REPLAY"
DEFAULT_START = datetime(2026, 8, 17, 6, 0, tzinfo=timezone.utc)

#: The trajectory's four signals and the units the demo protocol demands.
SIGNAL_UNITS: tuple[tuple[str, MeasurementType, str], ...] = (
    ("heart_rate", MeasurementType.HEART_RATE, "bpm"),
    ("spo2", MeasurementType.SPO2, "%"),
    ("respiratory_rate", MeasurementType.RESPIRATORY_RATE, "breaths/min"),
    ("systolic_bp", MeasurementType.SYSTOLIC_BP, "mmHg"),
)


@dataclass
class ReplayWindow:
    """Everything observable about one replayed window."""

    window_index: int
    timestamp: datetime
    ground_truth_state: str

    heart_rate: float
    spo2: float
    respiratory_rate: float

    # None on the first window: no predecessor, so no delta exists.
    heart_rate_delta: float | None = None
    spo2_delta: float | None = None
    respiratory_rate_delta: float | None = None

    anomaly_score: float | None = None
    predicted_anomaly: int | None = None

    risk_level: str = "UNKNOWN"          # effective — what the protocol acted on
    provider_level: str = "UNKNOWN"      # what the model said before the gate
    risk_score: float = 0.0
    confidence: float = 0.0
    risk_provider: str = ""
    model_version: str = ""
    degraded: bool = False
    gated: bool = False

    data_quality: str = "OK"
    accepted: int = 0
    rejected: int = 0

    transition: str | None = None
    interventions: list[str] = field(default_factory=list)
    next_dose: str | None = None
    contributing_factors: list[dict[str, Any]] = field(default_factory=list)
    likely_patterns: list[str] = field(default_factory=list)

    @property
    def scored(self) -> bool:
        return self.anomaly_score is not None

    @property
    def features(self) -> tuple[float, ...] | None:
        if not self.scored:
            return None
        return (
            self.heart_rate,
            self.spo2,
            self.respiratory_rate,
            self.heart_rate_delta,
            self.spo2_delta,
            self.respiratory_rate_delta,
        )


def load_trajectory(path: Path | None = None) -> dict[str, Any]:
    """The exported research trajectory. Regenerate it in the research repo."""
    fixture = path or TRAJECTORY_FIXTURE
    if not fixture.exists():
        raise FileNotFoundError(
            f"Missing {fixture}. In the research repository run "
            "`.venv/bin/python export_inference_fixtures.py`."
        )
    return json.loads(fixture.read_text())


def build_app(store_dir: Path, risk_provider: str = "synthetic_ml"):
    """The whole application over throwaway stores."""
    service = ScreeningService(repository=JsonRepository(store_dir / "store.json"))
    return create_app(
        service=service,
        monitoring=MonitoringContext.build(
            service.repository,
            monitoring_repository=JsonMonitoringRepository(
                store_dir / "monitoring.json"
            ),
            risk_provider=build_risk_provider(risk_provider),
        ),
    )


def observation_payload(
    window: dict[str, Any], patient_id: str, trial_id: str, at: datetime
) -> list[dict[str, Any]]:
    """One window as the ingestion endpoint's request rows."""
    return [
        {
            "patient_id": patient_id,
            "trial_id": trial_id,
            "recorded_at": at.isoformat(),
            "measurement_type": measurement.value,
            "value": window["observed"][signal],
            "unit": unit,
            "source": "SYNTHETIC",
            "device_id": "SYNTH-REPLAY",
            "quality_note": f"synthetic:replay:w{window['window_index']}",
        }
        for signal, measurement, unit in SIGNAL_UNITS
        if signal in window["observed"]
    ]


def replay(
    client,
    trajectory: dict[str, Any],
    patient_id: str = DEFAULT_PATIENT,
    trial_id: str = DEFAULT_TRIAL,
    start: datetime = DEFAULT_START,
    first: int = 0,
    last: int | None = None,
    verify_consistency: bool = True,
) -> list[ReplayWindow]:
    """Push windows through the API in order and capture what came back."""
    minutes = trajectory["window_minutes"]
    windows = trajectory["windows"]
    if last is not None:
        windows = windows[first : last + 1]
    elif first:
        windows = windows[first:]

    engine = default_engine()
    replayed: list[ReplayWindow] = []

    for offset, window in enumerate(windows):
        at = start + timedelta(minutes=minutes * offset)

        ingested = client.post(
            "/monitoring/observations",
            json={
                "observations": observation_payload(window, patient_id, trial_id, at),
                "now": at.isoformat(),
            },
        )
        ingested.raise_for_status()
        ingestion = ingested.json()

        cycled = client.post(
            f"/monitoring/patients/{patient_id}/cycle",
            json={"trial_id": trial_id, "now": at.isoformat()},
        )
        cycled.raise_for_status()
        cycle = cycled.json()
        risk = cycle["risk"]

        # Read the record back out through the API and rebuild the vector the
        # provider was given. This never touches the store directly.
        stored = client.get(
            f"/monitoring/patients/{patient_id}/observations",
            params={"trial_id": trial_id},
        )
        stored.raise_for_status()
        result = engine.score(
            PatientWindowState.from_observations(
                patient_id, [_observation(row) for row in stored.json()]
            )
        )
        features = dict(result.feature_values)

        entry = ReplayWindow(
            window_index=window["window_index"],
            timestamp=at,
            ground_truth_state=window["ground_truth_state"],
            heart_rate=window["observed"]["heart_rate"],
            spo2=window["observed"]["spo2"],
            respiratory_rate=window["observed"]["respiratory_rate"],
            heart_rate_delta=features.get("heart_rate_delta"),
            spo2_delta=features.get("spo2_delta"),
            respiratory_rate_delta=features.get("respiratory_rate_delta"),
            anomaly_score=result.anomaly_score,
            predicted_anomaly=result.predicted_anomaly,
            risk_level=cycle["effective_risk"]["level"],
            provider_level=cycle["effective_risk"]["provider_level"],
            risk_score=risk["score"],
            confidence=risk["confidence"],
            risk_provider=risk["provider"],
            model_version=risk["model_version"],
            degraded=risk["degraded"],
            gated=cycle["effective_risk"]["gated"],
            data_quality=cycle["state"]["data_quality"]["status"],
            accepted=ingestion["accepted_count"],
            rejected=len(ingestion["rejected"]),
            transition=(
                cycle["transition"]["trigger"] if cycle.get("transition") else None
            ),
            interventions=[i["action"] for i in cycle["interventions"]],
            next_dose=(
                cycle["next_dose"]["decision"] if cycle.get("next_dose") else None
            ),
            contributing_factors=risk["contributing_factors"],
            likely_patterns=risk["likely_patterns"],
        )

        if verify_consistency and risk["provider"] == "synthetic_ml":
            _assert_matches_the_cycle(entry, result)

        replayed.append(entry)

    return replayed


def _observation(row: dict[str, Any]):
    """Rehydrate an API observation row into the canonical model."""
    from app.schema.monitoring import Observation

    return Observation(**row)


def _assert_matches_the_cycle(entry: ReplayWindow, result) -> None:
    """Tie the recomputed score to the verdict the cycle actually returned.

    Without this the harness would be reporting a second, parallel inference and
    quietly calling it the application's. With it, a divergence between what ran
    inside the cycle and what is displayed here is a hard failure.
    """
    if not result.scored:
        if entry.provider_level != "UNKNOWN":
            raise AssertionError(
                f"window {entry.window_index}: recomputation found no scoreable "
                f"vector, but the cycle returned {entry.provider_level}"
            )
        return

    expected_level = _level_for(result).value
    expected_score = _display_score(result.anomaly_score)

    if expected_level != entry.provider_level:
        raise AssertionError(
            f"window {entry.window_index}: recomputed level {expected_level} != "
            f"cycle's provider level {entry.provider_level}"
        )
    if abs(expected_score - entry.risk_score) > 1e-9:
        raise AssertionError(
            f"window {entry.window_index}: recomputed display score "
            f"{expected_score} != cycle's {entry.risk_score}"
        )
