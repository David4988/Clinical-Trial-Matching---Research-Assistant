"""JSON-file monitoring store for Phase 2.

Deliberately a *separate file* from the Phase 1 screening store: monitoring
writes are far more frequent than screening writes, and keeping them apart means
observation traffic never rewrites screening results (and vice versa).

The atomic write is the same technique as `json_repo.py` — write to a temp file
beside the target, then one `os.replace`. An interrupted run cannot leave a
truncated store behind.

Observations, events and adverse events are bucketed by `patient_id` so a
per-patient read does not scan every row in the trial.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import RepositoryError
from .monitoring_base import MonitoringRepository
from ..schema.monitoring import AdverseEvent, Observation, TreatmentAssignment
from ..schema.monitoring_result import (
    MonitoringCycleResult,
    MonitoringEvent,
    Notification,
)

DEFAULT_STORE = Path(__file__).resolve().parents[2] / "data" / "monitoring.json"

_EMPTY: dict[str, dict[str, Any]] = {
    "treatments": {},
    "observations": {},
    "adverse_events": {},
    "cycles": {},
    "events": {},
    "notifications": {},
}


class JsonMonitoringRepository(MonitoringRepository):
    """Monitoring store with a validity-checked in-memory cache.

    Monitoring is write-heavy in a way screening never was: a single cycle
    touches the store several times, and a demo cohort runs dozens of cycles.
    Re-parsing the whole file on every call made that quadratic.

    The cache is keyed on the file's (mtime, size), so a store modified by
    anything else is picked up on the next read rather than served stale. Our
    own writes refresh the key.
    """

    def __init__(self, path: Path | str = DEFAULT_STORE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] | None = None
        self._cache_key: tuple[int, int] | None = None

    # -- storage primitives ------------------------------------------------

    def _file_key(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _load(self) -> dict[str, dict[str, Any]]:
        """Return the store. Callers may mutate the result, then `_write` it."""
        key = self._file_key()
        if self._cache is not None and key == self._cache_key:
            return self._cache

        if not self.path.exists():
            data = json.loads(json.dumps(_EMPTY))
        else:
            try:
                with self.path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                raise RepositoryError(
                    f"Could not read monitoring store at {self.path}: {exc}"
                ) from exc
            for section in _EMPTY:
                data.setdefault(section, {})

        self._cache, self._cache_key = data, key
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".monitoring-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, default=str)
                os.replace(tmp_name, self.path)
            except Exception:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise RepositoryError(
                f"Could not write monitoring store at {self.path}: {exc}"
            ) from exc

        self._cache, self._cache_key = data, self._file_key()

    # -- treatments --------------------------------------------------------

    def save_treatment(self, treatment: TreatmentAssignment) -> None:
        data = self._load()
        data["treatments"][treatment.treatment_id] = treatment.model_dump(mode="json")
        self._write(data)

    def get_treatment(self, treatment_id: str) -> TreatmentAssignment | None:
        raw = self._load()["treatments"].get(treatment_id)
        return TreatmentAssignment.model_validate(raw) if raw else None

    def list_treatments(
        self, trial_id: str | None = None, patient_id: str | None = None
    ) -> list[TreatmentAssignment]:
        treatments = [
            TreatmentAssignment.model_validate(raw)
            for raw in self._load()["treatments"].values()
        ]
        if trial_id is not None:
            treatments = [t for t in treatments if t.trial_id == trial_id]
        if patient_id is not None:
            treatments = [t for t in treatments if t.patient_id == patient_id]
        treatments.sort(key=lambda t: t.registered_at)
        return treatments

    # -- observations ------------------------------------------------------

    def save_observations(self, observations: list[Observation]) -> None:
        """One read, one write, regardless of batch size."""
        if not observations:
            return
        data = self._load()
        bucket = data["observations"]
        for observation in observations:
            bucket.setdefault(observation.patient_id, []).append(
                observation.model_dump(mode="json")
            )
        self._write(data)

    def list_observations(
        self,
        patient_id: str,
        trial_id: str | None = None,
        since: datetime | None = None,
    ) -> list[Observation]:
        rows = self._load()["observations"].get(patient_id, [])
        observations = [Observation.model_validate(raw) for raw in rows]
        if trial_id is not None:
            observations = [o for o in observations if o.trial_id == trial_id]
        if since is not None:
            observations = [o for o in observations if o.recorded_at >= since]
        observations.sort(key=lambda o: o.recorded_at)
        return observations

    # -- adverse events ----------------------------------------------------

    def save_adverse_event(self, event: AdverseEvent) -> None:
        data = self._load()
        bucket = data["adverse_events"].setdefault(event.patient_id, [])
        # An AE can be updated (resolved), so replace by id rather than append.
        for index, existing in enumerate(bucket):
            if existing.get("event_id") == event.event_id:
                bucket[index] = event.model_dump(mode="json")
                break
        else:
            bucket.append(event.model_dump(mode="json"))
        self._write(data)

    def list_adverse_events(self, patient_id: str) -> list[AdverseEvent]:
        rows = self._load()["adverse_events"].get(patient_id, [])
        events = [AdverseEvent.model_validate(raw) for raw in rows]
        events.sort(key=lambda e: e.onset_at)
        return events

    # -- monitoring cycles -------------------------------------------------

    def save_cycle(self, cycle: MonitoringCycleResult) -> None:
        data = self._load()
        data["cycles"][cycle.cycle_id] = cycle.model_dump(mode="json")
        self._write(data)

    def get_cycle(self, cycle_id: str) -> MonitoringCycleResult | None:
        raw = self._load()["cycles"].get(cycle_id)
        return MonitoringCycleResult.model_validate(raw) if raw else None

    def latest_cycle(self, patient_id: str) -> MonitoringCycleResult | None:
        """Newest cycle for a patient.

        Selects on the raw rows and validates only the winner. Building every
        stored cycle into a Pydantic model just to sort them was the single
        most expensive thing in a monitoring run.
        """
        rows = [
            raw
            for raw in self._load()["cycles"].values()
            if raw.get("patient_id") == patient_id
        ]
        if not rows:
            return None
        # ISO-8601 timestamps sort lexicographically.
        newest = max(rows, key=lambda raw: raw.get("generated_at") or "")
        return MonitoringCycleResult.model_validate(newest)

    def list_cycles(self, patient_id: str | None = None) -> list[MonitoringCycleResult]:
        cycles = [
            MonitoringCycleResult.model_validate(raw)
            for raw in self._load()["cycles"].values()
        ]
        if patient_id is not None:
            cycles = [c for c in cycles if c.patient_id == patient_id]
        cycles.sort(key=lambda c: c.generated_at, reverse=True)
        return cycles

    # -- timeline ----------------------------------------------------------

    def append_events(self, events: list[MonitoringEvent]) -> None:
        if not events:
            return
        data = self._load()
        bucket = data["events"]
        for event in events:
            bucket.setdefault(event.patient_id, []).append(event.model_dump(mode="json"))
        self._write(data)

    def list_events(self, patient_id: str) -> list[MonitoringEvent]:
        rows = self._load()["events"].get(patient_id, [])
        events = [MonitoringEvent.model_validate(raw) for raw in rows]
        events.sort(key=lambda e: e.occurred_at)
        return events

    # -- notifications -----------------------------------------------------

    def save_notifications(self, notifications: list[Notification]) -> None:
        if not notifications:
            return
        data = self._load()
        for notification in notifications:
            data["notifications"][notification.notification_id] = (
                notification.model_dump(mode="json")
            )
        self._write(data)

    def list_notifications(
        self, patient_id: str | None = None
    ) -> list[Notification]:
        notifications = [
            Notification.model_validate(raw)
            for raw in self._load()["notifications"].values()
        ]
        if patient_id is not None:
            notifications = [n for n in notifications if n.patient_id == patient_id]
        notifications.sort(key=lambda n: n.created_at, reverse=True)
        return notifications
