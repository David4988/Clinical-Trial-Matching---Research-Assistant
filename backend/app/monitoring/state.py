"""The Patient State Engine.

`build_patient_state` is a pure function of its arguments. It reads nothing,
writes nothing, and calls no clock — `now` is passed in. Two consequences worth
stating plainly:

  * The same inputs always produce the same state, so a demo trajectory can be
    replayed exactly and a test can assert on a fixed answer.
  * There is no stored state to fall out of date, so there is no cache to
    invalidate in a clinical decision path.

This mirrors `ScreeningService.screen()`, which computes a `ScreeningResult`
fresh from its inputs rather than mutating a stored record.

The engine deliberately contains no risk logic and no ML. It reports what the
record says — current values, movement from the patient's own baseline, and
whether the record can be trusted — and stops there.
"""

from __future__ import annotations

from datetime import datetime

from . import protocol, quality
from ..schema.monitoring import AdverseEvent, Observation, TreatmentAssignment
from ..schema.monitoring_enums import MeasurementType, TrendDirection
from ..schema.monitoring_result import MeasurementSummary, PatientState


def build_patient_state(
    patient_id: str,
    trial_id: str,
    observations: list[Observation],
    now: datetime,
    treatment: TreatmentAssignment | None = None,
    adverse_events: list[AdverseEvent] | None = None,
) -> PatientState:
    """Project everything known about a patient into a single deterministic view."""
    relevant = sorted(
        (o for o in observations if o.trial_id == trial_id),
        key=lambda o: o.recorded_at,
    )

    by_type: dict[MeasurementType, list[Observation]] = {}
    for observation in relevant:
        by_type.setdefault(observation.measurement_type, []).append(observation)

    measurements = [
        _summarise(measurement_type, rows, now)
        for measurement_type, rows in sorted(by_type.items(), key=lambda kv: kv[0].value)
    ]

    active_events = [e for e in (adverse_events or []) if e.is_active]

    return PatientState(
        patient_id=patient_id,
        trial_id=trial_id,
        as_of=now,
        treatment=treatment,
        measurements=measurements,
        recent_observations=relevant[-protocol.RECENT_OBSERVATION_LIMIT :],
        active_adverse_events=active_events,
        data_quality=quality.assess(relevant, now=now),
        observation_count=len(relevant),
    )


def _summarise(
    measurement_type: MeasurementType, rows: list[Observation], now: datetime
) -> MeasurementSummary:
    """One measurement's baseline, current value and movement between them."""
    latest = rows[-1]

    # Baseline is the patient's own starting point, not a population norm: a
    # trial patient is their own control.
    baseline_rows = rows[: protocol.BASELINE_SAMPLE_COUNT]
    baseline = sum(r.value for r in baseline_rows) / len(baseline_rows)

    recent = [r for r in rows if now - r.recorded_at <= protocol.RECENT_WINDOW]
    slope = _slope_per_hour(recent)

    return MeasurementSummary(
        measurement_type=measurement_type,
        unit=latest.unit,
        baseline=round(baseline, 3),
        current=latest.value,
        latest_at=latest.recorded_at,
        delta_from_baseline=round(latest.value - baseline, 3),
        trend=_trend(measurement_type, recent, slope),
        slope_per_hour=None if slope is None else round(slope, 4),
        sample_count=len(rows),
        is_stale=(now - latest.recorded_at) > protocol.STALE_AFTER,
    )


def _slope_per_hour(rows: list[Observation]) -> float | None:
    """Least-squares slope in units per hour, or None if not computable.

    Returns None rather than 0.0 when there is nothing to fit, so "flat" and
    "unknown" stay distinguishable — the same distinction Phase 1 draws between
    FALSE and UNKNOWN.
    """
    if len(rows) < protocol.MIN_SAMPLES_FOR_TREND:
        return None

    origin = rows[0].recorded_at
    xs = [(r.recorded_at - origin).total_seconds() / 3600.0 for r in rows]
    ys = [r.value for r in rows]

    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)

    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        # Every reading shares a timestamp; there is no time axis to fit.
        return None

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return numerator / denominator


def _trend(
    measurement_type: MeasurementType,
    recent: list[Observation],
    slope: float | None,
) -> TrendDirection:
    if slope is None or len(recent) < protocol.MIN_SAMPLES_FOR_TREND:
        return TrendDirection.INSUFFICIENT_DATA
    if abs(slope) < protocol.flat_slope_for(measurement_type):
        return TrendDirection.STABLE
    return TrendDirection.RISING if slope > 0 else TrendDirection.FALLING
