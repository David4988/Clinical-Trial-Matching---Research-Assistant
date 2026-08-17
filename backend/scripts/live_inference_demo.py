"""Drive three live monitoring windows through the real trained model.

    .venv/bin/python scripts/live_inference_demo.py

Nothing here is precomputed. Each window is ingested through the ordinary
`ObservationIngestionService`, a full `MonitoringService.run_cycle` is run over
it, and the RED/AMBER/GREEN that comes out is whatever the frozen Isolation
Forest returned for the six features derived from that window and the one
before it. No verdict is asserted or hard-coded anywhere in this file.

The first window is deliberately left in the output as UNKNOWN: it has no
predecessor, so three of the six features do not exist, and nothing is invented
to fill them.

Systolic BP is sent alongside the three model signals because the demo protocol
requires it for the record to be trustworthy. The model never sees it.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.monitoring.context import MonitoringContext  # noqa: E402
from app.repository.json_monitoring import JsonMonitoringRepository  # noqa: E402
from app.repository.json_repo import JsonRepository  # noqa: E402
from app.risk.factory import build_risk_provider  # noqa: E402
from app.schema.monitoring import Observation  # noqa: E402
from app.schema.monitoring_enums import MeasurementType, ObservationSource  # noqa: E402

PATIENT = "P-LIVE-001"
TRIAL = "CT-LIVE"
START = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)

M = MeasurementType

#: (heart rate, SpO2, respiratory rate, systolic BP) per five-minute window.
WINDOWS: tuple[tuple[float, float, float, float], ...] = (
    (70.0, 98.0, 15.0, 120.0),
    (72.0, 98.0, 15.0, 121.0),
    (88.0, 94.0, 21.0, 118.0),
)

UNITS = {
    M.HEART_RATE: "bpm",
    M.SPO2: "%",
    M.RESPIRATORY_RATE: "breaths/min",
    M.SYSTOLIC_BP: "mmHg",
}


def observations(index: int, at: datetime, row: tuple[float, ...]) -> list[Observation]:
    types = (M.HEART_RATE, M.SPO2, M.RESPIRATORY_RATE, M.SYSTOLIC_BP)
    return [
        Observation(
            observation_id=f"OBS-{PATIENT}-{index:02d}-{measurement.value}",
            patient_id=PATIENT,
            trial_id=TRIAL,
            recorded_at=at,
            source=ObservationSource.SYNTHETIC,
            measurement_type=measurement,
            value=value,
            unit=UNITS[measurement],
            device_id="SYNTH-LIVE",
            quality_note="synthetic:live-inference-demo",
        )
        for measurement, value in zip(types, row)
    ]


def main() -> int:
    provider = build_risk_provider("synthetic_ml")
    if provider.name != "synthetic_ml":
        print(
            "The live ML provider could not be built — the model artifact or "
            "scikit-learn is missing. Nothing was demonstrated.",
            file=sys.stderr,
        )
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        context = MonitoringContext.build(
            screening_repository=JsonRepository(root / "store.json"),
            monitoring_repository=JsonMonitoringRepository(root / "monitoring.json"),
            risk_provider=provider,
        )

        print()
        print(f"provider {provider.name}    model {provider.version}")
        print("=" * 104)
        print(
            f"{'t':>3}  {'HR':>6} {'SpO2':>6} {'RR':>6}  "
            f"{'ΔHR':>7} {'ΔSpO2':>7} {'ΔRR':>7}  "
            f"{'score':>10} {'flag':>5}  {'level':<8} {'source'}"
        )
        print("-" * 104)

        cycles = []
        for index, row in enumerate(WINDOWS):
            at = START + timedelta(minutes=5 * index)
            context.ingestion.ingest(observations(index, at, row), now=at)
            cycle = context.monitoring.run_cycle(PATIENT, TRIAL, at)
            cycles.append(cycle)

            risk = cycle.risk
            factors = {f.factor: f for f in risk.contributing_factors}
            forest = factors.get("ISOLATION_FOREST")

            if forest is None:
                # The window was not scored — no predecessor, so no deltas.
                deltas = ("—", "—", "—")
                score = "—"
                flag = "—"
            else:
                # Read the deltas back out of the evidence the provider built,
                # rather than recomputing them here — the point is to show what
                # the model was actually given.
                deltas = tuple(
                    _delta(factors, measurement)
                    for measurement in (M.HEART_RATE, M.SPO2, M.RESPIRATORY_RATE)
                )
                score = _model_score(forest)
                flag = "YES" if forest and forest.weight == 1.0 else "no"

            print(
                f"t{index:<2}  {row[0]:>6.1f} {row[1]:>6.1f} {row[2]:>6.1f}  "
                f"{deltas[0]:>7} {deltas[1]:>7} {deltas[2]:>7}  "
                f"{score:>10} {flag:>5}  {cycle.effective_risk.level.value:<8} "
                f"{risk.provider}"
            )

        print("-" * 104)
        print()
        for index, cycle in enumerate(cycles):
            print(f"t{index}: {cycle.risk.likely_patterns[0]}")
            if cycle.effective_risk.gated:
                print(f"     gate: {cycle.effective_risk.reason}")
            for intervention in cycle.interventions:
                print(
                    f"     protocol: {intervention.action.value} "
                    f"({intervention.protocol_rule_id})"
                )
        print()

    return 0


def _delta(factors: dict, measurement: MeasurementType) -> str:
    factor = factors.get(measurement.value)
    if factor is None:
        return "—"
    # "88 bpm at this window, +16 since the previous window. …"
    for token in factor.detail.split():
        if token.startswith(("+", "-")) and token[1:].replace(".", "", 1).isdigit():
            return token
    return "—"


def _model_score(forest) -> str:
    if forest is None:
        return "—"
    for token in forest.detail.split():
        if token.startswith(("+", "-")) and token[1:].replace(".", "", 1).isdigit():
            return token
    return "—"


if __name__ == "__main__":
    raise SystemExit(main())
