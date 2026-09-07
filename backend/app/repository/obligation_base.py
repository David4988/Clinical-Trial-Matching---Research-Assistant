"""Persistence abstraction for the obligation layer.

A sibling of `Repository` / `MonitoringRepository`, not an extension of
either — same reasoning as `monitoring_base.py`: a stable, small interface
that `JsonObligationRepository` and `SqlObligationRepository` both implement
exactly, and that `obligations/service.py` depends on and nothing else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime

from .base import RepositoryError  # noqa: F401  (re-exported for obligation callers)
from ..schema.obligations import (
    ApprovalRecord,
    IncomingMessage,
    Obligation,
    ObligationAction,
    ProposedAction,
    ResponsibleParty,
)


class ObligationRepository(ABC):
    @abstractmethod
    def transaction(self) -> AbstractContextManager[None]:
        """All writes inside the block commit together or not at all."""

    # -- parties -------------------------------------------------------

    @abstractmethod
    def save_party(self, party: ResponsibleParty) -> None: ...

    @abstractmethod
    def get_party(self, party_id: str) -> ResponsibleParty | None: ...

    @abstractmethod
    def list_parties(self, trial_id: str | None = None) -> list[ResponsibleParty]: ...

    # -- obligations -----------------------------------------------------

    @abstractmethod
    def save_obligation(self, obligation: Obligation) -> None: ...

    @abstractmethod
    def get_obligation(self, obligation_id: str) -> Obligation | None: ...

    @abstractmethod
    def list_obligations(
        self,
        trial_id: str | None = None,
        patient_id: str | None = None,
        status: str | None = None,
        type: str | None = None,
        party_id: str | None = None,
    ) -> list[Obligation]: ...

    @abstractmethod
    def list_active_scope(
        self, trial_id: str, patient_id: str, detector_source: str
    ) -> list[Obligation]:
        """Every non-terminal obligation for this (trial, patient, source) —
        the `DetectionScope` pre-filter `reconcile()` requires."""

    # -- follow-up ledger --------------------------------------------------

    @abstractmethod
    def append_actions(self, actions: list[ObligationAction]) -> None:
        """Append-only. Never update, never delete."""

    @abstractmethod
    def list_actions(self, obligation_id: str) -> list[ObligationAction]:
        """`seq` order, oldest first."""

    # -- proposals -----------------------------------------------------

    @abstractmethod
    def save_proposal(self, proposal: ProposedAction) -> None: ...

    @abstractmethod
    def get_proposal(self, proposal_id: str) -> ProposedAction | None: ...

    @abstractmethod
    def list_proposals(
        self,
        status: str | None = None,
        obligation_id: str | None = None,
        trial_id: str | None = None,
    ) -> list[ProposedAction]: ...

    @abstractmethod
    def has_pending_proposal(self, obligation_id: str) -> bool:
        """True iff an undecided (`DRAFT`) proposal exists for this
        obligation — the §6.3/§8.1 "at most one" rule."""

    # -- approvals -----------------------------------------------------

    @abstractmethod
    def save_approval(self, approval: ApprovalRecord) -> None: ...

    @abstractmethod
    def get_approval(self, proposal_id: str) -> ApprovalRecord | None: ...

    # -- inbound messages ------------------------------------------------

    @abstractmethod
    def find_incoming_message(self, channel: str, provider_message_id: str) -> IncomingMessage | None:
        """The idempotency check (§9.4 `inbound_idempotent`): a duplicate
        webhook delivery or a re-read poll must be discarded, not re-ledgered."""

    @abstractmethod
    def save_incoming_message(self, message: IncomingMessage) -> None: ...

    @abstractmethod
    def list_incoming_messages(self, unmatched: bool = False) -> list[IncomingMessage]: ...

    @abstractmethod
    def find_proposal_by_thread_id(self, provider_thread_id: str) -> ProposedAction | None:
        """Deterministic matching, priority 1 (§19.3): a stored Gmail
        `threadId` from a prior execution."""

    @abstractmethod
    def find_proposal_by_provider_message_id(self, provider_message_id: str) -> ProposedAction | None:
        """Deterministic matching, priority 1 for WhatsApp: the `wamid` a
        reply's `context.id` points back to."""

    @abstractmethod
    def has_active_whatsapp_session(self, phone: str, now: datetime, window_hours: float = 24.0) -> bool:
        """True iff an inbound WhatsApp message from `phone` arrived within
        `window_hours` — the customer-service window Meta's Cloud API opens
        for free-form replies after a customer-initiated message. Computed
        from `incoming_messages`, never assumed or cached."""
