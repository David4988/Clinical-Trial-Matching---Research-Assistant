"""Deterministic synthetic monitoring data.

=============================================================================
THIS IS NOT CLINICAL DATA.

Every value produced here is fabricated by interpolating between invented
endpoints. It exists so the monitoring pipeline can be developed, tested and
demonstrated without a patient. It carries `ObservationSource.SYNTHETIC` so it
is self-labelling everywhere it travels.
=============================================================================

Observations are *longitudinal*: each patient follows a trajectory through
time, and every reading is a point on that curve plus bounded noise. They are
not independent random rows — a random row cannot produce a trend, and a trend
is the entire thing Phase 2 exists to detect.

Determinism: seeded via `random.Random(seed)`. The same seed always yields
byte-identical output, so a demo scenario can be replayed exactly.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from enum import Enum

from ..schema.monitoring import Observation
from ..schema.monitoring_enums import MeasurementType, ObservationSource

M = MeasurementType

#: Short codes so a generated observation id stays readable on the timeline.
_CODES: dict[MeasurementType, str] = {
    M.HEART_RATE: "HR",
    M.SYSTOLIC_BP: "SBP",
    M.DIASTOLIC_BP: "DBP",
    M.SPO2: "SPO2",
    M.TEMPERATURE: "TMP",
    M.RESPIRATORY_RATE: "RR",
}


class Trajectory(str, Enum):
    STABLE = "STABLE"
    IMPROVING = "IMPROVING"
    GRADUAL_DETERIORATION = "GRADUAL_DETERIORATION"
    SUDDEN_DETERIORATION = "SUDDEN_DETERIORATION"
    RECOVERY = "RECOVERY"
    NOISY_SENSOR = "NOISY_SENSOR"


UNITS: dict[MeasurementType, str] = {
    M.HEART_RATE: "bpm",
    M.SYSTOLIC_BP: "mmHg",
    M.DIASTOLIC_BP: "mmHg",
    M.SPO2: "%",
    M.TEMPERATURE: "C",
    M.RESPIRATORY_RATE: "breaths/min",
}

#: SYNTHETIC. A comfortable, unremarkable set of vitals.
_HEALTHY: dict[MeasurementType, float] = {
    M.HEART_RATE: 72.0,
    M.SYSTOLIC_BP: 120.0,
    M.DIASTOLIC_BP: 78.0,
    M.SPO2: 98.0,
    M.TEMPERATURE: 36.8,
    M.RESPIRATORY_RATE: 14.0,
}

#: SYNTHETIC. Mildly off — chosen to land in the AMBER band, not RED.
_MILD: dict[MeasurementType, float] = {
    M.HEART_RATE: 112.0,
    M.SYSTOLIC_BP: 94.0,
    M.DIASTOLIC_BP: 58.0,
    M.SPO2: 92.5,
    M.TEMPERATURE: 38.0,
    M.RESPIRATORY_RATE: 24.0,
}

#: SYNTHETIC. Clearly breaching the protocol's concern bands.
_SEVERE: dict[MeasurementType, float] = {
    M.HEART_RATE: 142.0,
    M.SYSTOLIC_BP: 88.0,
    M.DIASTOLIC_BP: 52.0,
    M.SPO2: 86.0,
    M.TEMPERATURE: 39.0,
    M.RESPIRATORY_RATE: 31.0,
}

#: Noise amplitude per measurement — small enough not to swamp the trajectory.
_NOISE: dict[MeasurementType, float] = {
    M.HEART_RATE: 1.8,
    M.SYSTOLIC_BP: 2.2,
    M.DIASTOLIC_BP: 1.8,
    M.SPO2: 0.4,
    M.TEMPERATURE: 0.08,
    M.RESPIRATORY_RATE: 0.7,
}

#: (start, end) endpoints per trajectory.
_ENDPOINTS: dict[Trajectory, tuple[dict, dict]] = {
    Trajectory.STABLE: (_HEALTHY, _HEALTHY),
    Trajectory.IMPROVING: (_MILD, _HEALTHY),
    Trajectory.GRADUAL_DETERIORATION: (_HEALTHY, _SEVERE),
    Trajectory.SUDDEN_DETERIORATION: (_HEALTHY, _SEVERE),
    Trajectory.RECOVERY: (_SEVERE, _HEALTHY),
    Trajectory.NOISY_SENSOR: (_HEALTHY, _HEALTHY),
}

#: Fraction of the run after which a sudden deterioration begins.
_SUDDEN_ONSET = 0.55
#: Fraction of readings a failing sensor drops.
_DROPOUT_RATE = 0.35
#: Chance a failing sensor emits an impossible value (which ingestion refuses).
_SPIKE_RATE = 0.06
#: Point at which the SpO2 probe detaches entirely and readings simply stop.
#: This is what drives the UNKNOWN path: a protocol-required measurement goes
#: missing, so no current verdict is supportable and the trust gate says so.
#: The gap is never back-filled — absent data stays absent.
_SENSOR_LOSS_AFTER = 0.5


def _progress(trajectory: Trajectory, t: float) -> float:
    """Blend factor from start endpoint to end endpoint at fraction `t`."""
    if trajectory is Trajectory.SUDDEN_DETERIORATION:
        if t < _SUDDEN_ONSET:
            return 0.0
        return (t - _SUDDEN_ONSET) / (1.0 - _SUDDEN_ONSET)
    return t


def generate_observations(
    patient_id: str,
    trial_id: str,
    trajectory: Trajectory,
    start: datetime,
    hours: float = 8.0,
    interval_minutes: int = 15,
    seed: int = 42,
    measurement_types: tuple[MeasurementType, ...] = tuple(_HEALTHY),
) -> list[Observation]:
    """One patient's longitudinal record, oldest reading first."""
    rng = random.Random(seed)
    begin, end = _ENDPOINTS[trajectory]

    steps = max(int((hours * 60) // interval_minutes), 1)
    observations: list[Observation] = []

    for step in range(steps + 1):
        t = step / steps
        blend = _progress(trajectory, t)
        recorded_at = start + timedelta(minutes=step * interval_minutes)

        for measurement_type in measurement_types:
            if trajectory is Trajectory.NOISY_SENSOR:
                if measurement_type is M.SPO2 and t > _SENSOR_LOSS_AFTER:
                    # The probe has come off. Readings stop; nothing is invented
                    # to cover the gap.
                    continue
                if rng.random() < _DROPOUT_RATE:
                    # A dropped reading is simply absent — never back-filled.
                    continue

            base = begin[measurement_type]
            target = end[measurement_type]
            value = base + (target - base) * blend
            value += rng.uniform(-1.0, 1.0) * _NOISE[measurement_type]

            if trajectory is Trajectory.NOISY_SENSOR and rng.random() < _SPIKE_RATE:
                # A hardware glitch: physiologically impossible, so the
                # ingestion validator refuses it and reports the rejection.
                value *= 9.0

            observations.append(
                Observation(
                    # Derived from position, not uuid4 — a random id would
                    # break the "same seed, identical output" guarantee.
                    observation_id=(
                        f"OBS-{patient_id}-{step:04d}-{_CODES[measurement_type]}"
                    ),
                    patient_id=patient_id,
                    trial_id=trial_id,
                    recorded_at=recorded_at,
                    source=ObservationSource.SYNTHETIC,
                    measurement_type=measurement_type,
                    value=round(value, 2),
                    unit=UNITS[measurement_type],
                    device_id=f"SYNTH-{patient_id}",
                    quality_note=f"synthetic:{trajectory.value}",
                )
            )

    return observations


def generate_windowed(
    patient_id: str,
    trial_id: str,
    trajectory: Trajectory,
    start: datetime,
    windows: int = 4,
    hours: float = 8.0,
    interval_minutes: int = 15,
    seed: int = 42,
) -> list[list[Observation]]:
    """The same record, split into consecutive batches.

    Used to drive the demo: each window is ingested in turn and a monitoring
    cycle is run, so the risk level moves across several assessments rather
    than jumping in one step.
    """
    observations = generate_observations(
        patient_id,
        trial_id,
        trajectory,
        start,
        hours=hours,
        interval_minutes=interval_minutes,
        seed=seed,
    )
    if windows < 1:
        return [observations]

    by_time: dict[datetime, list[Observation]] = {}
    for observation in observations:
        by_time.setdefault(observation.recorded_at, []).append(observation)

    stamps = sorted(by_time)
    size = max(len(stamps) // windows, 1)
    chunks: list[list[Observation]] = []
    for index in range(0, len(stamps), size):
        batch: list[Observation] = []
        for stamp in stamps[index : index + size]:
            batch.extend(by_time[stamp])
        chunks.append(batch)

    # Fold any remainder into the last window so `windows` batches come back.
    while len(chunks) > windows:
        chunks[-2].extend(chunks.pop())
    return chunks


#: The demo cohort: one patient per trajectory, for the Trial Overview.
COHORT: tuple[tuple[str, Trajectory], ...] = (
    ("P-2001", Trajectory.STABLE),
    ("P-2002", Trajectory.IMPROVING),
    ("P-2003", Trajectory.GRADUAL_DETERIORATION),
    ("P-2004", Trajectory.SUDDEN_DETERIORATION),
    ("P-2005", Trajectory.RECOVERY),
    ("P-2006", Trajectory.NOISY_SENSOR),
)


def generate_cohort(
    trial_id: str,
    start: datetime,
    hours: float = 8.0,
    interval_minutes: int = 15,
    seed: int = 42,
) -> dict[str, list[Observation]]:
    """One record per demo patient, keyed by patient id.

    Each patient gets a seed derived from the base seed, so the cohort as a
    whole is reproducible and no two patients share a noise sequence.
    """
    return {
        patient_id: generate_observations(
            patient_id,
            trial_id,
            trajectory,
            start,
            hours=hours,
            interval_minutes=interval_minutes,
            seed=seed + index,
        )
        for index, (patient_id, trajectory) in enumerate(COHORT)
    }
