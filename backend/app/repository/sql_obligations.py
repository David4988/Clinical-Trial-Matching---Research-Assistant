"""PostgreSQL implementation of `ObligationRepository`.

Mechanical, same shape as `sql_repo.py`: `model_dump`/`model_validate` via
`db/mappers.py`, upserts via `pg_insert(...).on_conflict_do_update(...)`.
The one thing the JSON implementation cannot offer and this one does for
free: `obligations_active_key`, the partial unique index backing the
deduplication guarantee (`docs/FINAL_IMPLEMENTATION_PLAN.md` §9.4, §11.1) —
a bug in `reconcile()`'s scope guard becomes a loud `IntegrityError` here
instead of a silent duplicate.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..db import mappers
from ..db.session import SessionScopedRepository
from ..db.tables import (
    approval_records,
    incoming_messages,
    obligation_actions,
    obligations,
    proposed_actions,
    responsible_parties,
)
from ..schema.obligations import (
    ApprovalRecord,
    IncomingMessage,
    Obligation,
    ObligationAction,
    ProposedAction,
    ResponsibleParty,
)
from .base import RepositoryError
from .obligation_base import ObligationRepository


class SqlObligationRepository(SessionScopedRepository, ObligationRepository):
    def __init__(self, engine: Engine) -> None:
        SessionScopedRepository.__init__(self, engine)

    # -- parties -------------------------------------------------------

    def save_party(self, party: ResponsibleParty) -> None:
        row = mappers.party_to_row(party)
        stmt = pg_insert(responsible_parties).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=[responsible_parties.c.party_id], set_=row)
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save party: {exc}") from exc

    def get_party(self, party_id: str) -> ResponsibleParty | None:
        try:
            with self._session() as session:
                row = session.execute(
                    select(responsible_parties).where(responsible_parties.c.party_id == party_id)
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read party: {exc}") from exc
        return mappers.row_to_party(row) if row else None

    def list_parties(self, trial_id: str | None = None) -> list[ResponsibleParty]:
        try:
            with self._session() as session:
                rows = session.execute(select(responsible_parties)).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list parties: {exc}") from exc
        parties = [mappers.row_to_party(row) for row in rows]
        if trial_id:
            parties = [p for p in parties if trial_id in p.trial_ids]
        return parties

    # -- obligations -----------------------------------------------------

    def save_obligation(self, obligation: Obligation) -> None:
        row = mappers.obligation_to_row(obligation)
        stmt = pg_insert(obligations).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=[obligations.c.obligation_id], set_=row)
        try:
            with self._session() as session:
                session.execute(stmt)
        except IntegrityError as exc:
            raise RepositoryError(f"OBLIGATION_KEY_CONFLICT: {exc}") from exc
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save obligation: {exc}") from exc

    def get_obligation(self, obligation_id: str) -> Obligation | None:
        try:
            with self._session() as session:
                row = session.execute(
                    select(obligations).where(obligations.c.obligation_id == obligation_id)
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read obligation: {exc}") from exc
        return mappers.row_to_obligation(row) if row else None

    def list_obligations(
        self,
        trial_id: str | None = None,
        patient_id: str | None = None,
        status: str | None = None,
        type: str | None = None,
        party_id: str | None = None,
    ) -> list[Obligation]:
        query = select(obligations)
        if trial_id:
            query = query.where(obligations.c.trial_id == trial_id)
        if patient_id:
            query = query.where(obligations.c.patient_id == patient_id)
        if status:
            query = query.where(obligations.c.status == status)
        if type:
            query = query.where(obligations.c.type == type)
        if party_id:
            query = query.where(obligations.c.responsible_party_id == party_id)
        query = query.order_by(obligations.c.first_detected_at.desc())
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list obligations: {exc}") from exc
        return [mappers.row_to_obligation(row) for row in rows]

    def list_active_scope(self, trial_id: str, patient_id: str, detector_source: str) -> list[Obligation]:
        query = (
            select(obligations)
            .where(obligations.c.trial_id == trial_id)
            .where(obligations.c.patient_id == patient_id)
            .where(obligations.c.detector_source == detector_source)
            .where(obligations.c.status.in_(["OPEN", "AWAITING_RESPONSE"]))
        )
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read obligation scope: {exc}") from exc
        return [mappers.row_to_obligation(row) for row in rows]

    # -- follow-up ledger --------------------------------------------------

    def append_actions(self, actions: list[ObligationAction]) -> None:
        if not actions:
            return
        rows = [mappers.obligation_action_to_row(a) for a in actions]
        try:
            with self._session() as session:
                session.execute(obligation_actions.insert(), rows)
        except IntegrityError as exc:
            raise RepositoryError(f"LEDGER_ORDER_CONFLICT: {exc}") from exc
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not append actions: {exc}") from exc

    def list_actions(self, obligation_id: str) -> list[ObligationAction]:
        query = (
            select(obligation_actions)
            .where(obligation_actions.c.obligation_id == obligation_id)
            .order_by(obligation_actions.c.seq.asc())
        )
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list actions: {exc}") from exc
        return [mappers.row_to_obligation_action(row) for row in rows]

    # -- proposals -----------------------------------------------------

    def save_proposal(self, proposal: ProposedAction) -> None:
        row = mappers.proposed_action_to_row(proposal)
        stmt = pg_insert(proposed_actions).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=[proposed_actions.c.proposal_id], set_=row)
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save proposal: {exc}") from exc

    def get_proposal(self, proposal_id: str) -> ProposedAction | None:
        try:
            with self._session() as session:
                row = session.execute(
                    select(proposed_actions).where(proposed_actions.c.proposal_id == proposal_id)
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read proposal: {exc}") from exc
        return mappers.row_to_proposed_action(row) if row else None

    def list_proposals(
        self,
        status: str | None = None,
        obligation_id: str | None = None,
        trial_id: str | None = None,
    ) -> list[ProposedAction]:
        query = select(proposed_actions)
        if status:
            query = query.where(proposed_actions.c.status == status)
        if trial_id:
            query = query.where(proposed_actions.c.trial_id == trial_id)
        query = query.order_by(proposed_actions.c.created_at.desc())
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list proposals: {exc}") from exc
        proposals = [mappers.row_to_proposed_action(row) for row in rows]
        if obligation_id:
            proposals = [p for p in proposals if obligation_id in p.obligation_ids]
        return proposals

    def has_pending_proposal(self, obligation_id: str) -> bool:
        return len(self.list_proposals(status="DRAFT", obligation_id=obligation_id)) > 0

    # -- approvals -----------------------------------------------------

    def save_approval(self, approval: ApprovalRecord) -> None:
        row = mappers.approval_record_to_row(approval)
        stmt = pg_insert(approval_records).values(**row)
        stmt = stmt.on_conflict_do_update(index_elements=[approval_records.c.proposal_id], set_=row)
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save approval: {exc}") from exc

    def get_approval(self, proposal_id: str) -> ApprovalRecord | None:
        try:
            with self._session() as session:
                row = session.execute(
                    select(approval_records).where(approval_records.c.proposal_id == proposal_id)
                ).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read approval: {exc}") from exc
        return mappers.row_to_approval_record(row) if row else None

    # -- inbound messages ------------------------------------------------

    def find_incoming_message(self, channel: str, provider_message_id: str) -> IncomingMessage | None:
        query = (
            select(incoming_messages)
            .where(incoming_messages.c.channel == channel)
            .where(incoming_messages.c.provider_message_id == provider_message_id)
        )
        try:
            with self._session() as session:
                row = session.execute(query).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read incoming message: {exc}") from exc
        return mappers.row_to_incoming_message(row) if row else None

    def save_incoming_message(self, message: IncomingMessage) -> None:
        row = mappers.incoming_message_to_row(message)
        stmt = pg_insert(incoming_messages).values(**row)
        # Idempotent on the real constraint: a duplicate (channel,
        # provider_message_id) is discarded, not an error — exactly the
        # webhook-retry / re-polled-message case this table exists for.
        stmt = stmt.on_conflict_do_nothing(index_elements=["channel", "provider_message_id"])
        try:
            with self._session() as session:
                session.execute(stmt)
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not save incoming message: {exc}") from exc

    def list_incoming_messages(self, unmatched: bool = False) -> list[IncomingMessage]:
        query = select(incoming_messages)
        if unmatched:
            query = query.where(incoming_messages.c.obligation_id.is_(None))
        query = query.order_by(incoming_messages.c.received_at.desc())
        try:
            with self._session() as session:
                rows = session.execute(query).mappings().all()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not list incoming messages: {exc}") from exc
        return [mappers.row_to_incoming_message(row) for row in rows]

    def find_proposal_by_thread_id(self, provider_thread_id: str) -> ProposedAction | None:
        query = select(proposed_actions).where(proposed_actions.c.exec_provider_thread_id == provider_thread_id)
        try:
            with self._session() as session:
                row = session.execute(query).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read proposal by thread id: {exc}") from exc
        return mappers.row_to_proposed_action(row) if row else None

    def find_proposal_by_provider_message_id(self, provider_message_id: str) -> ProposedAction | None:
        query = select(proposed_actions).where(proposed_actions.c.exec_provider_message_id == provider_message_id)
        try:
            with self._session() as session:
                row = session.execute(query).mappings().first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not read proposal by provider message id: {exc}") from exc
        return mappers.row_to_proposed_action(row) if row else None

    def has_active_whatsapp_session(self, phone: str, now: datetime, window_hours: float = 24.0) -> bool:
        cutoff = now - timedelta(hours=window_hours)
        query = (
            select(incoming_messages.c.message_id)
            .where(incoming_messages.c.channel == "WHATSAPP")
            .where(incoming_messages.c.from_address == phone)
            .where(incoming_messages.c.received_at >= cutoff)
            .limit(1)
        )
        try:
            with self._session() as session:
                row = session.execute(query).first()
        except SQLAlchemyError as exc:
            raise RepositoryError(f"Could not check WhatsApp session state: {exc}") from exc
        return row is not None
