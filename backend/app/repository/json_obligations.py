"""JSON-file repository for the obligation layer — the rollback path.

Same atomic-write discipline as `json_repo.py` / `json_monitoring.py`. Note
it offers none of the database's structural guarantees (the partial unique
index on `obligation_key`, `UNIQUE(obligation_id, seq)`, the "one pending
proposal" index) — those are enforced here only by `obligations/service.py`'s
own logic, which is exactly why PostgreSQL, not this file, is the target
(`docs/FINAL_IMPLEMENTATION_PLAN.md` §9.1, §11.5).
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .obligation_base import ObligationRepository
from .paths import data_dir
from .base import RepositoryError
from .session_stub import json_transaction
from ..schema.obligations import (
    ApprovalRecord,
    IncomingMessage,
    Obligation,
    ObligationAction,
    ProposedAction,
    ResponsibleParty,
)

DEFAULT_STORE = data_dir() / "obligations.json"

_EMPTY: dict[str, dict[str, Any]] = {
    "parties": {},
    "obligations": {},
    "actions": {},  # obligation_id -> list[dict]
    "proposals": {},
    "approvals": {},
    "incoming_messages": {},
}


class JsonObligationRepository(ObligationRepository):
    def __init__(self, path: Path | str = DEFAULT_STORE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(_EMPTY))
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise RepositoryError(f"Could not read store at {self.path}: {exc}") from exc
        for key in _EMPTY:
            data.setdefault(key, {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        try:
            fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), prefix=".obligations-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, default=str)
                os.replace(tmp_name, self.path)
            except Exception:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise RepositoryError(f"Could not write store at {self.path}: {exc}") from exc

    def transaction(self) -> AbstractContextManager[None]:
        return json_transaction()

    # -- parties -------------------------------------------------------

    def save_party(self, party: ResponsibleParty) -> None:
        data = self._load()
        data["parties"][party.party_id] = party.model_dump(mode="json")
        self._write(data)

    def get_party(self, party_id: str) -> ResponsibleParty | None:
        raw = self._load()["parties"].get(party_id)
        return ResponsibleParty.model_validate(raw) if raw else None

    def list_parties(self, trial_id: str | None = None) -> list[ResponsibleParty]:
        parties = [ResponsibleParty.model_validate(raw) for raw in self._load()["parties"].values()]
        if trial_id:
            parties = [p for p in parties if trial_id in p.trial_ids]
        return parties

    # -- obligations -----------------------------------------------------

    def save_obligation(self, obligation: Obligation) -> None:
        data = self._load()
        data["obligations"][obligation.obligation_id] = obligation.model_dump(mode="json")
        self._write(data)

    def get_obligation(self, obligation_id: str) -> Obligation | None:
        raw = self._load()["obligations"].get(obligation_id)
        return Obligation.model_validate(raw) if raw else None

    def list_obligations(
        self,
        trial_id: str | None = None,
        patient_id: str | None = None,
        status: str | None = None,
        type: str | None = None,
        party_id: str | None = None,
    ) -> list[Obligation]:
        obligations = [Obligation.model_validate(raw) for raw in self._load()["obligations"].values()]
        if trial_id:
            obligations = [o for o in obligations if o.trial_id == trial_id]
        if patient_id:
            obligations = [o for o in obligations if o.patient_id == patient_id]
        if status:
            obligations = [o for o in obligations if o.status.value == status]
        if type:
            obligations = [o for o in obligations if o.type.value == type]
        if party_id:
            obligations = [o for o in obligations if o.responsible_party_id == party_id]
        obligations.sort(key=lambda o: o.first_detected_at, reverse=True)
        return obligations

    def list_active_scope(self, trial_id: str, patient_id: str, detector_source: str) -> list[Obligation]:
        return [
            o
            for o in self.list_obligations(trial_id=trial_id, patient_id=patient_id)
            if o.detector_source == detector_source and not o.is_terminal()
        ]

    # -- follow-up ledger --------------------------------------------------

    def append_actions(self, actions: list[ObligationAction]) -> None:
        if not actions:
            return
        data = self._load()
        for action in actions:
            bucket = data["actions"].setdefault(action.obligation_id, [])
            bucket.append(action.model_dump(mode="json"))
        self._write(data)

    def list_actions(self, obligation_id: str) -> list[ObligationAction]:
        raw = self._load()["actions"].get(obligation_id, [])
        actions = [ObligationAction.model_validate(r) for r in raw]
        actions.sort(key=lambda a: a.seq)
        return actions

    # -- proposals -----------------------------------------------------

    def save_proposal(self, proposal: ProposedAction) -> None:
        data = self._load()
        data["proposals"][proposal.proposal_id] = proposal.model_dump(mode="json")
        self._write(data)

    def get_proposal(self, proposal_id: str) -> ProposedAction | None:
        raw = self._load()["proposals"].get(proposal_id)
        return ProposedAction.model_validate(raw) if raw else None

    def list_proposals(
        self,
        status: str | None = None,
        obligation_id: str | None = None,
        trial_id: str | None = None,
    ) -> list[ProposedAction]:
        proposals = [ProposedAction.model_validate(raw) for raw in self._load()["proposals"].values()]
        if status:
            proposals = [p for p in proposals if p.status.value == status]
        if obligation_id:
            proposals = [p for p in proposals if obligation_id in p.obligation_ids]
        if trial_id:
            proposals = [p for p in proposals if p.trial_id == trial_id]
        proposals.sort(key=lambda p: p.created_at, reverse=True)
        return proposals

    def has_pending_proposal(self, obligation_id: str) -> bool:
        return any(True for _ in self.list_proposals(status="DRAFT", obligation_id=obligation_id))

    # -- approvals -----------------------------------------------------

    def save_approval(self, approval: ApprovalRecord) -> None:
        data = self._load()
        data["approvals"][approval.proposal_id] = approval.model_dump(mode="json")
        self._write(data)

    def get_approval(self, proposal_id: str) -> ApprovalRecord | None:
        raw = self._load()["approvals"].get(proposal_id)
        return ApprovalRecord.model_validate(raw) if raw else None

    # -- inbound messages ------------------------------------------------

    def find_incoming_message(self, channel: str, provider_message_id: str) -> IncomingMessage | None:
        for raw in self._load()["incoming_messages"].values():
            if raw["channel"] == channel and raw["provider_message_id"] == provider_message_id:
                return IncomingMessage.model_validate(raw)
        return None

    def save_incoming_message(self, message: IncomingMessage) -> None:
        data = self._load()
        data["incoming_messages"][message.message_id] = message.model_dump(mode="json")
        self._write(data)

    def list_incoming_messages(self, unmatched: bool = False) -> list[IncomingMessage]:
        messages = [IncomingMessage.model_validate(raw) for raw in self._load()["incoming_messages"].values()]
        if unmatched:
            messages = [m for m in messages if m.obligation_id is None]
        messages.sort(key=lambda m: m.received_at, reverse=True)
        return messages

    def find_proposal_by_thread_id(self, provider_thread_id: str) -> ProposedAction | None:
        for proposal in self.list_proposals():
            if proposal.execution and proposal.execution.provider_thread_id == provider_thread_id:
                return proposal
        return None

    def find_proposal_by_provider_message_id(self, provider_message_id: str) -> ProposedAction | None:
        for proposal in self.list_proposals():
            if proposal.execution and proposal.execution.provider_message_id == provider_message_id:
                return proposal
        return None

    def has_active_whatsapp_session(self, phone: str, now: datetime, window_hours: float = 24.0) -> bool:
        cutoff = now - timedelta(hours=window_hours)
        for raw in self._load()["incoming_messages"].values():
            if raw.get("channel") != "WHATSAPP" or raw.get("from_address") != phone:
                continue
            received_at = datetime.fromisoformat(raw["received_at"])
            if received_at >= cutoff:
                return True
        return False
