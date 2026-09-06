"""`ObligationService` — the only thing that persists a `reconcile()` delta.

Orchestrates: detector -> reconcile (pure) -> repository. Holds an
`ObligationRepository` and nothing else storage-shaped; no SQL, no session.
`docs/FINAL_IMPLEMENTATION_PLAN.md` §4, §6.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import ids, parties as parties_module, reconcile as reconcile_module
from .detectors import missing_lab
from ..repository.base import RepositoryError  # noqa: F401
from ..repository.obligation_base import ObligationRepository
from ..schema.enums import CriterionKind
from ..schema.obligation_enums import ActorKind, ObligationActionKind, ObligationStatus, ResolutionKind
from ..schema.obligations import DetectionScope, Obligation, ObligationAction, ObligationDelta, ObligationResolution
from ..schema.result import ScreeningResult


class ObligationError(ValueError):
    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


class ObligationService:
    def __init__(self, repository: ObligationRepository) -> None:
        self.repository = repository

    # -- detection / reconciliation -----------------------------------

    def detect_from_screening(
        self,
        result: ScreeningResult,
        now: datetime | None = None,
        has_active_treatment: bool = False,
    ) -> ObligationDelta:
        """Runs the missing-lab detector over one completed screening and
        reconciles it against every open obligation in this exact scope.
        Only ever called with a screening that ran to completion — a raised
        detector must never reach `reconcile()` (§6.4)."""
        now = now or datetime.now(timezone.utc)
        trial_id = result.trial.trial_id
        patient_id = result.patient.patient_id
        source = "SCREENING"

        detected = missing_lab.detect(result)
        existing = self.repository.list_active_scope(trial_id, patient_id, source)
        criterion_kind_by_ref = {c.criterion_id: c.kind for c in result.trial.criteria}
        parties = self.repository.list_parties(trial_id)

        def resolver(req):
            party = parties_module.resolve(req.trial_id, parties)
            return party.party_id if party else None

        delta = reconcile_module.reconcile(
            trial_id=trial_id,
            patient_id=patient_id,
            detector_source=source,
            detected=detected,
            existing=existing,
            now=now,
            criterion_kind_by_ref=criterion_kind_by_ref,
            has_active_treatment=has_active_treatment,
            responsible_party_id_for=resolver,
        )
        self._persist(delta)
        return delta

    def _persist(self, delta: ObligationDelta) -> None:
        with self.repository.transaction():
            for obligation in delta.all_obligations:
                self.repository.save_obligation(obligation)
            if delta.all_actions:
                self.repository.append_actions(delta.all_actions)

    # -- reads -----------------------------------------------------------

    def get(self, obligation_id: str) -> Obligation | None:
        return self.repository.get_obligation(obligation_id)

    def list(self, **filters) -> list[Obligation]:
        return self.repository.list_obligations(**filters)

    def list_actions(self, obligation_id: str) -> list[ObligationAction]:
        return self.repository.list_actions(obligation_id)

    # -- human actions -----------------------------------------------------

    def dismiss(self, obligation_id: str, reviewer: str, note: str, now: datetime | None = None) -> Obligation:
        now = now or datetime.now(timezone.utc)
        obligation = self.repository.get_obligation(obligation_id)
        if obligation is None:
            raise ObligationError("OBLIGATION_NOT_FOUND", f"No obligation with id '{obligation_id}'.")
        if obligation.is_terminal():
            raise ObligationError("OBLIGATION_TERMINAL", f"Obligation {obligation_id} is already terminal.")
        if not reviewer.strip():
            raise ObligationError("REVIEWER_REQUIRED", "Dismissal must record who made the decision.")
        if not note.strip():
            raise ObligationError("REVIEW_NOTE_REQUIRED", "Dismissal must record why.")

        dismissed = obligation.model_copy(
            update={
                "status": ObligationStatus.DISMISSED,
                "resolved_at": now,
                "resolution": ObligationResolution(
                    kind=ResolutionKind.DISMISSED, by=reviewer.strip(), note=note.strip(), at=now
                ),
            }
        )
        action = ObligationAction(
            action_id=ids.new_id(ids.OBLIGATION_ACTION),
            obligation_id=obligation_id,
            seq=obligation.action_count + 1,
            kind=ObligationActionKind.DISMISSED,
            occurred_at=now,
            actor_kind=ActorKind.RESEARCHER,
            actor_name=reviewer.strip(),
            note=note.strip(),
        )
        with self.repository.transaction():
            self.repository.save_obligation(dismissed)
            self.repository.append_actions([action])
        return dismissed

    def attach_action(self, obligation: Obligation, action: ObligationAction) -> Obligation:
        """Append a ledger entry and bump `action_count`/`last_action_at`.
        Refuses against a terminal obligation."""
        if obligation.is_terminal():
            raise ObligationError("OBLIGATION_TERMINAL", f"Obligation {obligation.obligation_id} is terminal.")
        updated = obligation.model_copy(
            update={"action_count": obligation.action_count + 1, "last_action_at": action.occurred_at}
        )
        with self.repository.transaction():
            self.repository.save_obligation(updated)
            self.repository.append_actions([action])
        return updated

    def mark_awaiting_response(self, obligation: Obligation) -> Obligation:
        updated = obligation.model_copy(
            update={
                "status": ObligationStatus.AWAITING_RESPONSE,
                "escalation_count": (
                    obligation.escalation_count + 1
                    if obligation.status is ObligationStatus.AWAITING_RESPONSE
                    else obligation.escalation_count
                ),
            }
        )
        self.repository.save_obligation(updated)
        return updated
