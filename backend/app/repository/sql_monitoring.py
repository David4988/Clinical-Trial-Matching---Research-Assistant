"""PostgreSQL implementation of `MonitoringRepository`.

Sibling to `sql_repo.py`, never inheriting from it — the same discipline the
JSON implementations already follow. Batch methods (`save_observations`,
`append_events`) become one multi-row insert instead of one JSON
read-modify-write, which is the concrete latency win this migration buys for
the monitoring ingestion path.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from ..db import mappers
from ..db.session import SessionScopedRepository
from ..db.tables import (
    adverse_events,
    monitoring_cycles,
    monitoring_events,
    notifications,
    observations,
    treatments,
)
from ..schema.monitoring import AdverseEvent, Observation, TreatmentAssignment
from ..schema.monitoring_result import (
    MonitoringCycleResult,
    MonitoringEvent,
    Notification,
)
from .base import RepositoryError
from .monitoring_base import MonitoringRepository


class SqlMonitoringRepository(SessionScopedRepository, MonitoringRepository):
    def __init__(self, engine: Engine) -> None:
        SessionScopedRepository.__init__(self, engine)

    # -- treatments --------------------------------------------------------

    def save_treatment(self, treatment: TreatmentAssignment) -> None:
        row = mappers.treatment_to_row(treatment)
        stmt = pg_insert(treatments).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[treatments.c.treatment_id], set_=row
        )
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save treatment: {exc}") from exc

    def get_treatment(self, treatment_id: str) -> TreatmentAssignment | None:
        try:
            with self._session() as session:
                row = session.execute(
                    select(treatments).where(treatments.c.treatment_id == treatment_id)
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read treatment: {exc}") from exc
        return mappers.row_to_treatment(row) if row else None

    def list_treatments(
        self, trial_id: str | None = None, patient_id: str | None = None
    ) -> list[TreatmentAssignment]:
        query = select(treatments)
        if trial_id is not None:
            query = query.where(treatments.c.trial_id == trial_id)
        if patient_id is not None:
            query = query.where(treatments.c.patient_id == patient_id)
        query = query.order_by(treatments.c.registered_at)
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list treatments: {exc}") from exc
        return [mappers.row_to_treatment(row) for row in rows]

    # -- observations --------------------------------------------------------

    def save_observations(self, observations_batch: list[Observation]) -> None:
        if not observations_batch:
            return
        rows = [mappers.observation_to_row(o) for o in observations_batch]
        try:
            with self._session() as session:
                session.execute(observations.insert(), rows)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save observations: {exc}") from exc

    def list_observations(
        self,
        patient_id: str,
        trial_id: str | None = None,
        since: datetime | None = None,
    ) -> list[Observation]:
        query = select(observations).where(observations.c.patient_id == patient_id)
        if trial_id is not None:
            query = query.where(observations.c.trial_id == trial_id)
        if since is not None:
            query = query.where(observations.c.recorded_at >= since)
        query = query.order_by(observations.c.recorded_at)
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list observations: {exc}") from exc
        return [mappers.row_to_observation(row) for row in rows]

    # -- adverse events --------------------------------------------------------

    def save_adverse_event(self, event: AdverseEvent) -> None:
        row = mappers.adverse_event_to_row(event)
        stmt = pg_insert(adverse_events).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[adverse_events.c.event_id], set_=row
        )
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save adverse event: {exc}") from exc

    def list_adverse_events(self, patient_id: str) -> list[AdverseEvent]:
        query = (
            select(adverse_events)
            .where(adverse_events.c.patient_id == patient_id)
            .order_by(adverse_events.c.onset_at)
        )
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list adverse events: {exc}") from exc
        return [mappers.row_to_adverse_event(row) for row in rows]

    # -- monitoring cycles --------------------------------------------------------

    def save_cycle(self, cycle: MonitoringCycleResult) -> None:
        row = mappers.monitoring_cycle_to_row(cycle)
        stmt = pg_insert(monitoring_cycles).values(**row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[monitoring_cycles.c.cycle_id], set_=row
        )
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save monitoring cycle: {exc}") from exc

    def get_cycle(self, cycle_id: str) -> MonitoringCycleResult | None:
        try:
            with self._session() as session:
                row = session.execute(
                    select(monitoring_cycles).where(
                        monitoring_cycles.c.cycle_id == cycle_id
                    )
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read monitoring cycle: {exc}") from exc
        return mappers.row_to_monitoring_cycle(row) if row else None

    def latest_cycle(self, patient_id: str) -> MonitoringCycleResult | None:
        query = (
            select(monitoring_cycles)
            .where(monitoring_cycles.c.patient_id == patient_id)
            .order_by(monitoring_cycles.c.generated_at.desc())
            .limit(1)
        )
        try:
            with self._session() as session:
                row = session.execute(query).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read latest cycle: {exc}") from exc
        return mappers.row_to_monitoring_cycle(row) if row else None

    def list_cycles(self, patient_id: str | None = None) -> list[MonitoringCycleResult]:
        query = select(monitoring_cycles)
        if patient_id is not None:
            query = query.where(monitoring_cycles.c.patient_id == patient_id)
        query = query.order_by(monitoring_cycles.c.generated_at.desc())
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list monitoring cycles: {exc}") from exc
        return [mappers.row_to_monitoring_cycle(row) for row in rows]

    # -- timeline --------------------------------------------------------

    def append_events(self, events: list[MonitoringEvent]) -> None:
        if not events:
            return
        rows = [mappers.monitoring_event_to_row(e) for e in events]
        try:
            with self._session() as session:
                session.execute(monitoring_events.insert(), rows)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not append monitoring events: {exc}") from exc

    def list_events(self, patient_id: str) -> list[MonitoringEvent]:
        query = (
            select(monitoring_events)
            .where(monitoring_events.c.patient_id == patient_id)
            .order_by(monitoring_events.c.occurred_at)
        )
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list monitoring events: {exc}") from exc
        return [mappers.row_to_monitoring_event(row) for row in rows]

    # -- notifications --------------------------------------------------------

    def save_notifications(self, notifications_batch: list[Notification]) -> None:
        if not notifications_batch:
            return
        try:
            with self._session() as session:
                for notification in notifications_batch:
                    row = mappers.notification_to_row(notification)
                    stmt = pg_insert(notifications).values(**row)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=[notifications.c.notification_id], set_=row
                    )
                    session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save notifications: {exc}") from exc

    def list_notifications(self, patient_id: str | None = None) -> list[Notification]:
        query = select(notifications)
        if patient_id is not None:
            query = query.where(notifications.c.patient_id == patient_id)
        query = query.order_by(notifications.c.created_at.desc())
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list notifications: {exc}") from exc
        return [mappers.row_to_notification(row) for row in rows]
