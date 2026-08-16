"""Data quality: what we can and cannot trust about a patient's record.

Two distinct jobs, deliberately separated.

`check_observation` runs at the boundary and answers "is this row a valid
measurement at all?". Impossible values and wrong units are recording errors,
so they are refused rather than stored — but the caller is always told what was
refused and why. Nothing is silently dropped.

`assess` runs when a PatientState is built and answers "can a verdict rest on
this record?". Its output drives the trust gate: an UNTRUSTWORTHY record forces
effective risk to UNKNOWN no matter what the risk provider returned.

The Phase 1 philosophy carries over intact — missing data is a finding, not a
gap to fill, and an empty reading is never read as a normal one.
"""

from __future__ import annotations

from datetime import datetime

from . import protocol
from ..schema.enums import Severity
from ..schema.monitoring import Observation
from ..schema.monitoring_enums import (
    DataQualityCode,
    DataQualityStatus,
    MeasurementType,
)
from ..schema.monitoring_result import DataQuality, DataQualityFlag


# -- boundary validation ---------------------------------------------------


def check_observation(observation: Observation) -> str | None:
    """Return why this observation is invalid, or None if it is usable."""
    expected = protocol.EXPECTED_UNITS.get(observation.measurement_type)
    reported = protocol.canonical_unit(observation.unit)

    if expected is not None and reported != expected:
        return (
            f"{observation.measurement_type.value} must be reported in "
            f"'{expected}'; got '{observation.unit}'. No conversion applied."
        )

    low, high = protocol.PLAUSIBLE_RANGE.get(
        observation.measurement_type, (float("-inf"), float("inf"))
    )
    if not low <= observation.value <= high:
        return (
            f"{observation.measurement_type.value} of {observation.value} is "
            f"outside the plausible range {low}–{high}; treated as a recording "
            "error, not as a clinical finding."
        )

    return None


# -- record-level assessment ----------------------------------------------


def assess(
    observations: list[Observation],
    now: datetime,
    required: tuple[MeasurementType, ...] = protocol.REQUIRED_MEASUREMENTS,
) -> DataQuality:
    """Grade the trustworthiness of a patient's observation record."""
    flags: list[DataQualityFlag] = []

    by_type: dict[MeasurementType, list[Observation]] = {}
    for observation in observations:
        by_type.setdefault(observation.measurement_type, []).append(observation)
    for rows in by_type.values():
        rows.sort(key=lambda o: o.recorded_at)

    missing = [m for m in required if not by_type.get(m)]
    if missing:
        flags.append(
            DataQualityFlag(
                code=DataQualityCode.MISSING_MEASUREMENT,
                severity=Severity.WARN,
                message=(
                    "The protocol requires "
                    + ", ".join(m.value for m in missing)
                    + "; no reading is recorded."
                ),
                measurement_types=list(missing),
            )
        )

    stale = [
        m
        for m in required
        if by_type.get(m) and now - by_type[m][-1].recorded_at > protocol.STALE_AFTER
    ]
    if stale:
        minutes = int(protocol.STALE_AFTER.total_seconds() // 60)
        flags.append(
            DataQualityFlag(
                code=DataQualityCode.STALE_OBSERVATION,
                severity=Severity.WARN,
                message=(
                    ", ".join(m.value for m in stale)
                    + f" has no reading within the last {minutes} minutes. "
                    "A current verdict cannot rest on it."
                ),
                measurement_types=list(stale),
            )
        )

    conflicting = _conflicting_types(by_type)
    if conflicting:
        flags.append(
            DataQualityFlag(
                code=DataQualityCode.CONFLICTING_OBSERVATIONS,
                severity=Severity.WARN,
                message=(
                    ", ".join(m.value for m in conflicting)
                    + " was reported more than once at effectively the same "
                    "time with materially different values. The most recent "
                    "reading was used."
                ),
                measurement_types=list(conflicting),
            )
        )

    if 0 < len(observations) < protocol.SPARSE_HISTORY_BELOW:
        flags.append(
            DataQualityFlag(
                code=DataQualityCode.SPARSE_HISTORY,
                severity=Severity.INFO,
                message=(
                    f"Only {len(observations)} observation(s) recorded; trends "
                    "are not yet meaningful."
                ),
            )
        )

    return DataQuality(status=_status_for(missing, stale, flags), flags=flags)


def _conflicting_types(
    by_type: dict[MeasurementType, list[Observation]],
) -> list[MeasurementType]:
    """Same measurement, near-simultaneous, materially different values."""
    conflicting: list[MeasurementType] = []
    for measurement_type, rows in by_type.items():
        for earlier, later in zip(rows, rows[1:]):
            if later.recorded_at - earlier.recorded_at > protocol.CONFLICT_WINDOW:
                continue
            scale = max(abs(earlier.value), 1.0)
            if abs(later.value - earlier.value) / scale > protocol.CONFLICT_RELATIVE_DELTA:
                conflicting.append(measurement_type)
                break
    return conflicting


def _status_for(
    missing: list[MeasurementType],
    stale: list[MeasurementType],
    flags: list[DataQualityFlag],
) -> DataQualityStatus:
    """Ordered, deterministic.

    Missing or stale *required* measurements mean no current verdict is
    supportable, so the record is UNTRUSTWORTHY and the gate will force UNKNOWN.
    Everything else is a caveat rather than a blocker.
    """
    if missing or stale:
        return DataQualityStatus.UNTRUSTWORTHY
    if flags:
        return DataQualityStatus.DEGRADED
    return DataQualityStatus.OK
