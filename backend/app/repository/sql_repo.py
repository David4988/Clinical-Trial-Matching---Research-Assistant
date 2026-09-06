"""PostgreSQL implementation of the Phase 1 screening `Repository`.

Mechanical by design: every method is the same `model_dump`/`model_validate`
round-trip the JSON implementation already does, over an upsert instead of a
whole-file rewrite. See `docs/FINAL_IMPLEMENTATION_PLAN.md` §11.3.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from ..db import mappers
from ..db.session import SessionScopedRepository
from ..db.tables import patients, screening_results, trials
from ..schema.clinical import Patient
from ..schema.result import ScreeningResult
from ..schema.trial import Trial
from .base import Repository, RepositoryError


class SqlRepository(SessionScopedRepository, Repository):
    def __init__(self, engine: Engine) -> None:
        SessionScopedRepository.__init__(self, engine)

    # -- Repository ----------------------------------------------------------

    def save_patient(self, patient: Patient) -> None:
        self._upsert_patient(patient)

    def save_trial(self, trial: Trial) -> None:
        self._upsert_trial(trial)

    def save_screening_result(self, result: ScreeningResult) -> None:
        try:
            with self.transaction():
                self._upsert_patient(result.patient)
                self._upsert_trial(result.trial)
                row = mappers.screening_result_to_row(result)
                stmt = pg_insert(screening_results).values(**row)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[screening_results.c.result_id], set_=row
                )
                with self._session() as session:
                    session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save screening result: {exc}") from exc

    def get_screening_result(self, result_id: str) -> ScreeningResult | None:
        try:
            with self._session() as session:
                row = session.execute(
                    select(screening_results).where(
                        screening_results.c.result_id == result_id
                    )
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read screening result: {exc}") from exc
        return mappers.row_to_screening_result(row) if row else None

    def list_screening_results(self) -> list[ScreeningResult]:
        try:
            with self._session() as session:
                rows = session.execute(
                    select(screening_results).order_by(
                        screening_results.c.generated_at.desc()
                    )
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list screening results: {exc}") from exc
        return [mappers.row_to_screening_result(row) for row in rows]

    # -- helpers ---------------------------------------------------------------

    def _upsert_patient(self, patient: Patient) -> None:
        now = datetime.now(timezone.utc)
        row = mappers.patient_to_row(patient, now)
        stmt = pg_insert(patients).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=[patients.c.patient_id], set_=row)
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save patient: {exc}") from exc

    def _upsert_trial(self, trial: Trial) -> None:
        now = datetime.now(timezone.utc)
        row = mappers.trial_to_row(trial, now)
        stmt = pg_insert(trials).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=[trials.c.trial_id], set_=row)
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save trial: {exc}") from exc
