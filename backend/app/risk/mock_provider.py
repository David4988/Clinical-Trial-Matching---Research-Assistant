"""Deterministic offline mock risk provider.

Design note: this computes, it does not replay
-----------------------------------------------
The mock derives its level from the actual measurements and trends in the
`PatientState` it is handed, scored against the demo protocol's bands. It holds
no script and no notion of "which demo step is this".

That matters. A provider that replayed a canned GREEN -> AMBER -> RED sequence
would make the demo theatre and would leave the provider seam untested: nothing
would prove that a real model receiving the same `PatientState` could produce
the same shape of answer. Because this one computes, a deteriorating synthetic
trajectory *causes* the escalation, and a recovering one *causes* the
de-escalation.

It is still a mock. The weights and bands are invented (see `protocol.py`), and
"prediction" here means "banding the current picture", not forecasting. A real
model replaces this file and nothing else.

No randomness anywhere: same state, same output, every run.
"""

from __future__ import annotations

from datetime import datetime

from .provider import RiskProvider
from ..monitoring import ids, protocol
from ..schema.monitoring_enums import (
    MeasurementType,
    RiskLevel,
    TrendDirection,
)
from ..schema.monitoring_result import (
    ContributingFactor,
    MeasurementSummary,
    PatientState,
    RiskAssessment,
)

#: SYNTHETIC. Added to a measurement's excursion when its trend moves further
#: away from the normal band — a value that is high *and climbing* is worse
#: than the same value holding steady.
TREND_PENALTY = 0.25

#: SYNTHETIC. Excursions are capped here so one wild reading cannot dominate.
EXCURSION_CAP = 1.5

#: SYNTHETIC. Composite blends the weighted mean with the single worst
#: measurement, because deterioration is often driven by one failing system
#: rather than by everything drifting together.
MEAN_SHARE = 0.5


class MockRiskProvider(RiskProvider):
    """Offline, deterministic, advisory."""

    name = "mock-risk-v1"
    version = "0.1.0"

    def assess(self, state: PatientState, now: datetime) -> RiskAssessment:
        try:
            return self._assess(state, now)
        except Exception as exc:  # noqa: BLE001 - advisory layer must never abort a cycle
            return RiskAssessment(
                assessment_id=ids.new_id(ids.RISK),
                patient_id=state.patient_id,
                trial_id=state.trial_id,
                assessed_at=now,
                level=RiskLevel.UNKNOWN,
                score=0.0,
                confidence=0.0,
                prediction_horizon_hours=protocol.PREDICTION_HORIZON_HOURS,
                contributing_factors=[],
                likely_patterns=[],
                provider=self.name,
                model_version=self.version,
                degraded=True,
            )

    # -- scoring -----------------------------------------------------------

    def _assess(self, state: PatientState, now: datetime) -> RiskAssessment:
        scored = [
            (summary, _excursion(summary))
            for summary in state.measurements
            if summary.current is not None
        ]

        if not scored:
            # Nothing measurable. The provider says so rather than guessing a
            # reassuring number.
            return RiskAssessment(
                assessment_id=ids.new_id(ids.RISK),
                patient_id=state.patient_id,
                trial_id=state.trial_id,
                assessed_at=now,
                level=RiskLevel.UNKNOWN,
                score=0.0,
                confidence=0.0,
                prediction_horizon_hours=protocol.PREDICTION_HORIZON_HOURS,
                likely_patterns=["No measurements available to assess."],
                provider=self.name,
                model_version=self.version,
            )

        total_weight = sum(
            protocol.RISK_WEIGHTS.get(s.measurement_type, 0.1) for s, _ in scored
        )
        weighted = sum(
            protocol.RISK_WEIGHTS.get(s.measurement_type, 0.1) * excursion
            for s, excursion in scored
        )
        mean_excursion = weighted / total_weight if total_weight else 0.0
        worst = max(excursion for _, excursion in scored)

        score = MEAN_SHARE * mean_excursion + (1.0 - MEAN_SHARE) * worst
        score += _adverse_event_load(state)
        score = min(max(score, 0.0), 1.0)

        return RiskAssessment(
            assessment_id=ids.new_id(ids.RISK),
            patient_id=state.patient_id,
            trial_id=state.trial_id,
            assessed_at=now,
            level=protocol.level_for_score(score),
            score=round(score, 4),
            confidence=round(_confidence(state), 4),
            prediction_horizon_hours=protocol.PREDICTION_HORIZON_HOURS,
            contributing_factors=_factors(scored, state),
            likely_patterns=_patterns(state),
            provider=self.name,
            model_version=self.version,
        )


# -- helpers ---------------------------------------------------------------


def _excursion(summary: MeasurementSummary) -> float:
    """How far outside the protocol's normal band this value sits.

    0.0 inside the band, 1.0 at the concern-band edge, capped above that.
    """
    measurement_type = summary.measurement_type
    value = summary.current
    if value is None:
        return 0.0

    normal = protocol.NORMAL_BAND.get(measurement_type)
    concern = protocol.CONCERN_BAND.get(measurement_type)
    if normal is None or concern is None:
        return 0.0

    normal_low, normal_high = normal
    concern_low, concern_high = concern

    if value > normal_high:
        span = max(concern_high - normal_high, 1e-6)
        excursion = (value - normal_high) / span
        drifting = summary.trend is TrendDirection.RISING
    elif value < normal_low:
        span = max(normal_low - concern_low, 1e-6)
        excursion = (normal_low - value) / span
        drifting = summary.trend is TrendDirection.FALLING
    else:
        # Inside the normal band contributes nothing, however it is moving.
        return 0.0

    if drifting:
        excursion += TREND_PENALTY

    return min(excursion, EXCURSION_CAP)


def _adverse_event_load(state: PatientState) -> float:
    """Active adverse events add to risk but never set the level alone."""
    return sum(
        protocol.ADVERSE_EVENT_WEIGHT.get(event.severity.value, 0.0)
        for event in state.active_adverse_events
    )


def _confidence(state: PatientState) -> float:
    """How much the provider trusts its own answer.

    Driven by how complete and how deep the record is. Deliberately independent
    of the score: being confident and being worried are different things.
    """
    required = protocol.REQUIRED_MEASUREMENTS
    present = [
        s
        for s in state.measurements
        if s.measurement_type in required and s.current is not None and not s.is_stale
    ]
    completeness = len(present) / len(required) if required else 1.0

    if state.measurements:
        average_samples = sum(s.sample_count for s in state.measurements) / len(
            state.measurements
        )
        depth = min(average_samples / (protocol.MIN_SAMPLES_FOR_TREND * 2), 1.0)
    else:
        depth = 0.0

    return min(max(0.30 + 0.40 * completeness + 0.30 * depth, 0.0), 1.0)


def _factors(
    scored: list[tuple[MeasurementSummary, float]], state: PatientState
) -> list[ContributingFactor]:
    """Explain the score: every measurement that pushed it up, worst first."""
    factors = [
        ContributingFactor(
            factor=summary.measurement_type.value,
            detail=(
                f"{summary.current} {summary.unit or ''}".strip()
                + f" is outside the protocol normal band "
                f"{protocol.NORMAL_BAND[summary.measurement_type]}"
                + (
                    f", and {summary.trend.value.lower()} "
                    f"({summary.slope_per_hour:+.2f}/h)"
                    if summary.slope_per_hour is not None
                    and summary.trend
                    in (TrendDirection.RISING, TrendDirection.FALLING)
                    else ""
                )
                + f". Baseline was {summary.baseline}."
            ),
            weight=round(min(excursion / EXCURSION_CAP, 1.0), 4),
            measurement_type=summary.measurement_type,
        )
        for summary, excursion in scored
        if excursion > 0
    ]
    factors.sort(key=lambda f: f.weight, reverse=True)

    for event in state.active_adverse_events:
        factors.append(
            ContributingFactor(
                factor="ADVERSE_EVENT",
                detail=f"Active adverse event recorded: {event.term} ({event.severity.value}).",
                weight=round(
                    protocol.ADVERSE_EVENT_WEIGHT.get(event.severity.value, 0.0), 4
                ),
            )
        )

    return factors


def _patterns(state: PatientState) -> list[str]:
    """Named shapes the mock recognises. Advisory prose, never parsed.

    Stands in for the kind of qualitative read a real model would offer.
    """
    patterns: list[str] = []

    def trend_of(measurement_type: MeasurementType) -> TrendDirection | None:
        summary = state.measurement(measurement_type)
        return summary.trend if summary else None

    heart_rate = trend_of(MeasurementType.HEART_RATE)
    spo2 = trend_of(MeasurementType.SPO2)
    respiratory = trend_of(MeasurementType.RESPIRATORY_RATE)
    systolic = trend_of(MeasurementType.SYSTOLIC_BP)

    if heart_rate is TrendDirection.RISING and spo2 is TrendDirection.FALLING:
        patterns.append(
            "Rising heart rate alongside falling oxygen saturation — the "
            "compensatory shape this demo protocol treats as deterioration."
        )
    if respiratory is TrendDirection.RISING and spo2 is TrendDirection.FALLING:
        patterns.append(
            "Increasing respiratory rate with falling saturation — rising work "
            "of breathing."
        )
    if heart_rate is TrendDirection.RISING and systolic is TrendDirection.FALLING:
        patterns.append(
            "Heart rate climbing while systolic pressure falls — a circulatory "
            "pattern worth a clinician's eye."
        )
    if heart_rate is TrendDirection.FALLING and spo2 is TrendDirection.RISING:
        patterns.append(
            "Heart rate settling and saturation improving — consistent with "
            "recovery toward baseline."
        )

    if not patterns:
        if all(
            t in (TrendDirection.STABLE, None)
            for t in (heart_rate, spo2, respiratory, systolic)
        ):
            patterns.append("No directional pattern; measurements are holding steady.")
        else:
            patterns.append("No recognised multi-measurement pattern.")

    return patterns
