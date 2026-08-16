"""THE DEMO PROTOCOL — SYNTHETIC VALUES, NOT CLINICAL GUIDANCE.

=============================================================================
EVERY NUMBER IN THIS FILE IS INVENTED FOR A HACKATHON DEMONSTRATION.

They are plausible-looking placeholders chosen to make a synthetic trajectory
legible on screen. They are NOT derived from any trial protocol, guideline, or
clinical literature, and must never be used to interpret a real patient.

A real deployment replaces this module wholesale with the actual protocol
document's criteria, and nothing else in the codebase should need to change.
=============================================================================

Every threshold Phase 2 uses lives here, so there is exactly one place to look
when a reviewer asks "where did that number come from?" — and exactly one place
to change when the answer is "the protocol says something different".

Consumers: quality.py, state.py, risk providers, interventions.py, next_dose.py.
"""

from __future__ import annotations

from datetime import timedelta

from ..schema.monitoring_enums import (
    InterventionAction,
    MeasurementType,
    RiskLevel,
)

PROTOCOL_ID = "DEMO-PROTOCOL-1"
PROTOCOL_LABEL = "Synthetic demonstration protocol (not clinical guidance)"

# -- units -----------------------------------------------------------------

#: The unit each measurement must be reported in. Anything else is rejected
#: rather than converted — the Phase 1 rule that a wrong unit is a wrong
#: clinical decision, carried into monitoring.
EXPECTED_UNITS: dict[MeasurementType, str] = {
    MeasurementType.HEART_RATE: "bpm",
    MeasurementType.SYSTOLIC_BP: "mmHg",
    MeasurementType.DIASTOLIC_BP: "mmHg",
    MeasurementType.SPO2: "%",
    MeasurementType.TEMPERATURE: "C",
    MeasurementType.RESPIRATORY_RATE: "breaths/min",
}

#: Notational variants that mean the same thing. Only spelling differences
#: belong here; anything needing arithmetic is a real conversion and is refused.
UNIT_ALIASES: dict[str, str] = {
    "bpm": "bpm",
    "beats/min": "bpm",
    "beats per minute": "bpm",
    "mmhg": "mmHg",
    "%": "%",
    "percent": "%",
    "pct": "%",
    "spo2%": "%",
    "c": "C",
    "°c": "C",
    "celsius": "C",
    "degc": "C",
    "breaths/min": "breaths/min",
    "breaths per minute": "breaths/min",
    "rpm": "breaths/min",
    "/min": "breaths/min",
}

# -- data validity ---------------------------------------------------------

#: SYNTHETIC. Outside this range a reading is treated as a recording error
#: rather than as a sick patient — a heart rate of 900 is a broken sensor.
PLAUSIBLE_RANGE: dict[MeasurementType, tuple[float, float]] = {
    MeasurementType.HEART_RATE: (20.0, 250.0),
    MeasurementType.SYSTOLIC_BP: (50.0, 300.0),
    MeasurementType.DIASTOLIC_BP: (20.0, 200.0),
    MeasurementType.SPO2: (50.0, 100.0),
    MeasurementType.TEMPERATURE: (25.0, 45.0),
    MeasurementType.RESPIRATORY_RATE: (4.0, 60.0),
}

#: SYNTHETIC. An observation older than this cannot support a current verdict.
STALE_AFTER = timedelta(minutes=90)

#: SYNTHETIC. Two readings of the same type this close together that disagree
#: by more than CONFLICT_RELATIVE_DELTA are contradictory.
CONFLICT_WINDOW = timedelta(minutes=2)
CONFLICT_RELATIVE_DELTA = 0.20

#: Measurements the protocol expects to be present for a complete assessment.
REQUIRED_MEASUREMENTS: tuple[MeasurementType, ...] = (
    MeasurementType.HEART_RATE,
    MeasurementType.SYSTOLIC_BP,
    MeasurementType.SPO2,
)

#: Below this many readings for a measurement, trends are not meaningful.
MIN_SAMPLES_FOR_TREND = 3
#: Below this many readings overall, the history is too thin to lean on.
SPARSE_HISTORY_BELOW = 5

#: How many of the earliest readings define a patient's own baseline.
BASELINE_SAMPLE_COUNT = 5
#: The window whose readings count as "current" for trend fitting.
RECENT_WINDOW = timedelta(hours=6)
#: Cap on observations carried inside a PatientState for display.
RECENT_OBSERVATION_LIMIT = 60

#: SYNTHETIC. A fitted slope is "flat" below this fraction of the measurement's
#: own normal-band width, per hour. Scaled per measurement because a single
#: absolute cut-point cannot serve both heart rate (band ~50 wide) and
#: temperature (band ~1.4 wide) — 0.35/hour is noise for one and a fever for
#: the other.
TREND_FLAT_BAND_FRACTION = 0.04

# -- observation bands -----------------------------------------------------

#: SYNTHETIC. Inside NORMAL_BAND contributes nothing to risk.
NORMAL_BAND: dict[MeasurementType, tuple[float, float]] = {
    MeasurementType.HEART_RATE: (50.0, 100.0),
    MeasurementType.SYSTOLIC_BP: (100.0, 140.0),
    MeasurementType.DIASTOLIC_BP: (60.0, 90.0),
    MeasurementType.SPO2: (95.0, 100.0),
    MeasurementType.TEMPERATURE: (36.1, 37.5),
    MeasurementType.RESPIRATORY_RATE: (12.0, 20.0),
}

#: SYNTHETIC. Outside CONCERN_BAND is a severe excursion.
CONCERN_BAND: dict[MeasurementType, tuple[float, float]] = {
    MeasurementType.HEART_RATE: (40.0, 130.0),
    MeasurementType.SYSTOLIC_BP: (85.0, 180.0),
    MeasurementType.DIASTOLIC_BP: (50.0, 110.0),
    MeasurementType.SPO2: (90.0, 100.0),
    MeasurementType.TEMPERATURE: (35.5, 38.5),
    MeasurementType.RESPIRATORY_RATE: (10.0, 26.0),
}

#: SYNTHETIC. How much each measurement contributes to the composite score.
RISK_WEIGHTS: dict[MeasurementType, float] = {
    MeasurementType.HEART_RATE: 0.22,
    MeasurementType.SYSTOLIC_BP: 0.20,
    MeasurementType.SPO2: 0.26,
    MeasurementType.RESPIRATORY_RATE: 0.16,
    MeasurementType.TEMPERATURE: 0.10,
    MeasurementType.DIASTOLIC_BP: 0.06,
}

# -- risk banding ----------------------------------------------------------

#: SYNTHETIC. Composite score -> triage level.
GREEN_BELOW = 0.30
AMBER_BELOW = 0.62

#: SYNTHETIC. How far ahead the demo risk layer claims to look.
PREDICTION_HORIZON_HOURS = 24

#: SYNTHETIC. Extra score added when an active adverse event is recorded.
ADVERSE_EVENT_WEIGHT = {"MILD": 0.05, "MODERATE": 0.15, "SEVERE": 0.30}


def level_for_score(score: float) -> RiskLevel:
    """Band a composite score. The only place the cut-points are applied."""
    if score < GREEN_BELOW:
        return RiskLevel.GREEN
    if score < AMBER_BELOW:
        return RiskLevel.AMBER
    return RiskLevel.RED


# -- protocol response -----------------------------------------------------

#: SYNTHETIC. Monitoring cadence mandated at each level.
MONITORING_INTERVAL_MINUTES: dict[RiskLevel, int] = {
    RiskLevel.GREEN: 240,
    RiskLevel.AMBER: 30,
    RiskLevel.RED: 5,
    RiskLevel.UNKNOWN: 15,
}

#: The action set each level mandates. This table IS the protocol response —
#: a risk provider cannot reach it, and cannot add to it.
ACTIONS_BY_LEVEL: dict[RiskLevel, tuple[InterventionAction, ...]] = {
    RiskLevel.GREEN: (InterventionAction.ROUTINE_MONITORING,),
    RiskLevel.AMBER: (
        InterventionAction.INCREASE_MONITORING,
        InterventionAction.CLINICAL_REVIEW,
        InterventionAction.NOTIFY_CLINICIAN,
    ),
    RiskLevel.RED: (
        InterventionAction.URGENT_ESCALATION,
        InterventionAction.NOTIFY_CLINICIAN,
        InterventionAction.INCREASE_MONITORING,
    ),
    RiskLevel.UNKNOWN: (
        InterventionAction.REQUEST_REPEAT_OBSERVATION,
        InterventionAction.CLINICAL_REVIEW,
        InterventionAction.NOTIFY_CLINICIAN,
    ),
}

#: Rule id per level, so every raised intervention cites a written rule.
RULE_IDS: dict[RiskLevel, str] = {
    RiskLevel.GREEN: "DEMO-GREEN-01",
    RiskLevel.AMBER: "DEMO-AMBER-01",
    RiskLevel.RED: "DEMO-RED-01",
    RiskLevel.UNKNOWN: "DEMO-UNKNOWN-01",
}

#: Plain-language statement of what each level means, shown to reviewers.
LEVEL_RATIONALE: dict[RiskLevel, str] = {
    RiskLevel.GREEN: "Observations sit within the protocol's normal bands.",
    RiskLevel.AMBER: (
        "One or more measurements are drifting outside the normal band. "
        "The protocol requires closer monitoring and clinical review."
    ),
    RiskLevel.RED: (
        "Measurements breach the protocol's concern bands. The protocol "
        "requires urgent escalation and holds the next dose for review."
    ),
    RiskLevel.UNKNOWN: (
        "The available data is not trustworthy enough to assess risk. The "
        "protocol requires repeat observations and explicitly does not treat "
        "this as a safe state."
    ),
}


def flat_slope_for(measurement_type: MeasurementType) -> float:
    """Slope per hour below which a measurement counts as STABLE."""
    low, high = NORMAL_BAND.get(measurement_type, (0.0, 1.0))
    return max(abs(high - low), 1e-6) * TREND_FLAT_BAND_FRACTION


def canonical_unit(unit: str | None) -> str | None:
    """Normalise a reported unit to its canonical spelling, or None."""
    if unit is None:
        return None
    cleaned = " ".join(unit.split()).casefold()
    if not cleaned:
        return None
    return UNIT_ALIASES.get(cleaned, cleaned)
