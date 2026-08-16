"""Persistence abstraction for Phase 2 monitoring entities.

A sibling of `Repository`, not an extension of it. Phase 1's interface stays
exactly five methods, so `JsonRepository` needs no change and a future
`SupabaseRepository` can be ported independently of monitoring.

`RepositoryError` is deliberately reused from `base.py` rather than redefined —
the API already maps it to a 503, and one persistence failure mode is enough.

Note `save_observations` is batch-only. Single-row saves would rewrite the whole
JSON store per observation, which is O(n) per row and would visibly stall a
high-frequency demo. Making the batch shape the *only* shape stops that being
reintroduced by accident.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from .base import RepositoryError  # noqa: F401  (re-exported for monitoring callers)
from ..schema.monitoring import AdverseEvent, Observation, TreatmentAssignment
from ..schema.monitoring_result import (
    MonitoringCycleResult,
    MonitoringEvent,
    Notification,
)


class MonitoringRepository(ABC):
    """Storage for treatments, observations, cycles, timeline events and alerts."""

    # -- treatments --------------------------------------------------------

    @abstractmethod
    def save_treatment(self, treatment: TreatmentAssignment) -> None: ...

    @abstractmethod
    def get_treatment(self, treatment_id: str) -> TreatmentAssignment | None: ...

    @abstractmethod
    def list_treatments(
        self, trial_id: str | None = None, patient_id: str | None = None
    ) -> list[TreatmentAssignment]: ...

    # -- observations ------------------------------------------------------

    @abstractmethod
    def save_observations(self, observations: list[Observation]) -> None:
        """Persist a batch. Implementations must write once, not once per row."""

    @abstractmethod
    def list_observations(
        self,
        patient_id: str,
        trial_id: str | None = None,
        since: datetime | None = None,
    ) -> list[Observation]:
        """Return observations in chronological order, oldest first."""

    # -- adverse events ----------------------------------------------------

    @abstractmethod
    def save_adverse_event(self, event: AdverseEvent) -> None: ...

    @abstractmethod
    def list_adverse_events(self, patient_id: str) -> list[AdverseEvent]: ...

    # -- monitoring cycles -------------------------------------------------

    @abstractmethod
    def save_cycle(self, cycle: MonitoringCycleResult) -> None:
        """Store a full cycle: state, risk, gate, interventions, dose decision."""

    @abstractmethod
    def get_cycle(self, cycle_id: str) -> MonitoringCycleResult | None: ...

    @abstractmethod
    def latest_cycle(self, patient_id: str) -> MonitoringCycleResult | None:
        """The previous cycle, used to derive risk transitions."""

    @abstractmethod
    def list_cycles(self, patient_id: str | None = None) -> list[MonitoringCycleResult]:
        """Newest first, matching `Repository.list_screening_results()`."""

    # -- timeline ----------------------------------------------------------

    @abstractmethod
    def append_events(self, events: list[MonitoringEvent]) -> None:
        """Append-only. Implementations must never rewrite an existing entry."""

    @abstractmethod
    def list_events(self, patient_id: str) -> list[MonitoringEvent]:
        """Chronological, oldest first — the timeline reads top-to-bottom."""

    # -- notifications -----------------------------------------------------

    @abstractmethod
    def save_notifications(self, notifications: list[Notification]) -> None: ...

    @abstractmethod
    def list_notifications(
        self, patient_id: str | None = None
    ) -> list[Notification]: ...
