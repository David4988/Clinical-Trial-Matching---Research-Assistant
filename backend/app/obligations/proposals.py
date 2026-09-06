"""`ObligationProposalService` — propose / approve / reject.

The approval boundary, stated as three facts (§8.2):

1. `execute()` accepts only `ApprovalRecord`.
2. `ApprovalRecord` is constructed in exactly one function: `approve()`
   below, and only after non-empty `reviewer` and `note`.
3. Therefore no code path exists from detection to external communication
   that does not pass through a human.

`approve()` calls `execute()` synchronously and folds a delivery failure
into `status: FAILED` — one researcher click, one outcome, one transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import ids, templates
from .execution import ChannelRequiresTemplateError, ExecutionService
from .service import ObligationError, ObligationService
from ..agent.investigate import investigate as run_investigation
from ..agent.model.provider import AgentModelProvider
from ..agent.model.template_provider import TemplateProvider
from ..comms.factory import build_delivery_provider
from ..repository.obligation_base import ObligationRepository
from ..agent.prompts import BANNED_PHRASES, PROMPT_VERSION
from ..schema.obligation_enums import ActorKind, ObligationActionKind, ObligationStatus, ProposalStatus, ProviderKind
from ..schema.obligations import (
    ApprovalRecord,
    ObligationAction,
    ProposalDecision,
    ProposalProvenance,
    ProposedAction,
)

_MAX_BODY_LENGTH = 4000
_BANNED_PHRASES = BANNED_PHRASES


def validate_draft(subject: str, body: str, recipient_exists: bool) -> list[str]:
    """Returns a list of problems; empty means the draft is usable as-is.
    §8.4: banned-phrase list, length ceiling, recipient must exist."""
    problems: list[str] = []
    if not subject.strip() or not body.strip():
        problems.append("Subject and body must not be empty.")
    if len(body) > _MAX_BODY_LENGTH:
        problems.append(f"Body exceeds the {_MAX_BODY_LENGTH}-character ceiling.")
    lowered = body.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            problems.append(f"Body contains a banned phrase: '{phrase}'.")
    if not recipient_exists:
        problems.append("Recipient party does not exist in the registry.")
    return problems


class ObligationProposalService:
    def __init__(
        self,
        repository: ObligationRepository,
        obligation_service: ObligationService,
        execution_service: ExecutionService,
        facade=None,
        model_provider: AgentModelProvider | None = None,
    ) -> None:
        self.repository = repository
        self.obligation_service = obligation_service
        self.execution_service = execution_service
        # Both optional so existing callers/tests that never wired the agent
        # keep working: `propose()` falls back to calling
        # `obligations/templates.py` directly (§12.4's "TemplateProvider
        # delegates to templates.py" collapses to the same code path when
        # neither a facade nor a provider was supplied).
        self.facade = facade
        self.model_provider = model_provider or TemplateProvider()

    # -- propose -----------------------------------------------------------

    def propose(self, obligation_id: str, now: datetime | None = None) -> ProposedAction:
        now = now or datetime.now(timezone.utc)
        obligation = self.repository.get_obligation(obligation_id)
        if obligation is None:
            raise ObligationError("OBLIGATION_NOT_FOUND", f"No obligation with id '{obligation_id}'.")
        if obligation.is_terminal():
            raise ObligationError("OBLIGATION_TERMINAL", f"Obligation {obligation_id} is terminal.")
        if self.repository.has_pending_proposal(obligation_id):
            raise ObligationError("PROPOSAL_PENDING", f"An undecided proposal already exists for {obligation_id}.")

        party = self.repository.get_party(obligation.responsible_party_id) if obligation.responsible_party_id else None
        recipient_party_id = party.party_id if party else "UNROUTED"
        channel = party.preferred_channel if party else None
        from ..schema.monitoring_enums import NotificationChannel

        channel = channel or NotificationChannel.IN_APP

        if self.facade is not None:
            run = run_investigation(obligation, self.facade, self.model_provider, now)
            subject, body, reason = run.output.subject, run.output.body, run.output.reason
            used_fallback = run.used_fallback
            provider_kind = run.result.provider_kind
            is_template = used_fallback or provider_kind is ProviderKind.TEMPLATE
            model_name = None if is_template else run.result.model_name
            generated_by = (
                "deterministic-template" if is_template else f"agent:{run.result.model_name}@{run.result.prompt_version}"
            )
            latency_ms = run.result.latency_ms
            tools_called = run.tools_called
            evidence_ids = run.evidence_ids
            model_unresolved = list(run.output.unresolved)
        else:
            # No agent wired up (e.g. a test constructing this service
            # directly) — the exact same deterministic drafting `templates.py`
            # always produced, unchanged.
            subject = templates.draft_subject(obligation)
            body = templates.draft_body(obligation)
            reason = templates.draft_reason(obligation)
            used_fallback = False
            provider_kind = ProviderKind.TEMPLATE
            model_name = None
            generated_by = "deterministic-template"
            latency_ms = None
            tools_called = []
            evidence_ids = [e.locator for e in obligation.evidence if e.locator]
            model_unresolved = []

        problems = validate_draft(subject, body, recipient_exists=party is not None)
        if problems:
            # A draft that fails validation is replaced by the deterministic
            # template — never silently dropped, never shown as if the model
            # had written it (§8.4).
            subject = templates.draft_subject(obligation)
            body = templates.draft_body(obligation)
            reason = templates.draft_reason(obligation)
            provider_kind = ProviderKind.TEMPLATE
            model_name = None
            generated_by = "deterministic-template"
        degraded = used_fallback or bool(problems)
        unresolved = [*model_unresolved, *problems]

        proposal = ProposedAction(
            proposal_id=ids.new_id(ids.PROPOSAL),
            obligation_ids=[obligation_id],
            trial_id=obligation.trial_id,
            patient_ids=[obligation.patient_id],
            action_type=templates.action_type_for(obligation),
            status=ProposalStatus.DRAFT,
            recipient_party_id=recipient_party_id,
            channel=channel,
            subject=subject,
            body=body,
            reason=reason,
            evidence=obligation.evidence,
            template_name=templates.TEMPLATE_NAME,
            template_params=templates.template_params_for(obligation),
            provenance=ProposalProvenance(
                generated_by=generated_by,
                provider_kind=provider_kind,
                model_name=model_name,
                prompt_version=PROMPT_VERSION if provider_kind is not ProviderKind.TEMPLATE else None,
                latency_ms=latency_ms,
                tools_called=tools_called,
                degraded=degraded,
                unresolved=unresolved,
                evidence_ids=evidence_ids,
            ),
            created_at=now,
        )

        action = ObligationAction(
            action_id=ids.new_id(ids.OBLIGATION_ACTION),
            obligation_id=obligation_id,
            seq=obligation.action_count + 1,
            kind=ObligationActionKind.PROPOSAL_CREATED,
            occurred_at=now,
            actor_kind=ActorKind.SYSTEM,
            ref_id=proposal.proposal_id,
        )

        with self.repository.transaction():
            self.repository.save_proposal(proposal)
            updated = obligation.model_copy(
                update={"action_count": obligation.action_count + 1, "last_action_at": now}
            )
            self.repository.save_obligation(updated)
            self.repository.append_actions([action])

        return proposal

    # -- decide --------------------------------------------------------

    def reject(self, proposal_id: str, reviewer: str, note: str, now: datetime | None = None) -> ProposedAction:
        now = now or datetime.now(timezone.utc)
        proposal = self._require_draft(proposal_id)
        self._require_reviewer_and_note(reviewer, note)

        decided = proposal.model_copy(
            update={
                "status": ProposalStatus.REJECTED,
                "decision": ProposalDecision(
                    outcome="REJECTED", reviewer=reviewer.strip(), note=note.strip(), decided_at=now
                ),
            }
        )
        obligation = self.repository.get_obligation(proposal.obligation_ids[0])
        action = ObligationAction(
            action_id=ids.new_id(ids.OBLIGATION_ACTION),
            obligation_id=proposal.obligation_ids[0],
            seq=(obligation.action_count + 1) if obligation else 1,
            kind=ObligationActionKind.PROPOSAL_REJECTED,
            occurred_at=now,
            actor_kind=ActorKind.RESEARCHER,
            actor_name=reviewer.strip(),
            note=note.strip(),
            ref_id=proposal_id,
        )
        with self.repository.transaction():
            self.repository.save_proposal(decided)
            if obligation is not None:
                self.repository.save_obligation(
                    obligation.model_copy(update={"action_count": obligation.action_count + 1, "last_action_at": now})
                )
            self.repository.append_actions([action])
        return decided

    def approve(
        self,
        proposal_id: str,
        reviewer: str,
        note: str,
        channel=None,
        edited_subject: str | None = None,
        edited_body: str | None = None,
        now: datetime | None = None,
    ) -> ProposedAction:
        now = now or datetime.now(timezone.utc)
        proposal = self._require_draft(proposal_id)
        self._require_reviewer_and_note(reviewer, note)

        obligation = self.repository.get_obligation(proposal.obligation_ids[0])
        if obligation is None:
            raise ObligationError("OBLIGATION_NOT_FOUND", f"No obligation with id '{proposal.obligation_ids[0]}'.")
        if obligation.is_terminal():
            raise ObligationError("OBLIGATION_TERMINAL", f"Obligation {obligation.obligation_id} is terminal.")

        final_channel = channel or proposal.channel
        final_subject = edited_subject or proposal.subject
        final_body = edited_body or proposal.body

        approval = ApprovalRecord(
            proposal_id=proposal_id,
            approved_by=reviewer.strip(),
            approved_at=now,
            channel=final_channel,
            subject=final_subject,
            body=final_body,
            template_name=proposal.template_name,
            template_params=proposal.template_params,
        )

        provider = build_delivery_provider(final_channel)
        try:
            execution = self.execution_service.execute(approval, proposal, provider, now)
        except ChannelRequiresTemplateError as exc:
            raise ObligationError("CHANNEL_REQUIRES_TEMPLATE", str(exc)) from exc

        final_status = ProposalStatus.EXECUTED if execution.delivery_status.value == "SENT" else ProposalStatus.FAILED
        decided = proposal.model_copy(
            update={
                "status": final_status,
                "decision": ProposalDecision(
                    outcome="APPROVED",
                    reviewer=reviewer.strip(),
                    note=note.strip(),
                    decided_at=now,
                    edited_subject=edited_subject,
                    edited_body=edited_body,
                ),
                "execution": execution,
            }
        )

        ledger_kind = ObligationActionKind.MESSAGE_SENT if final_status is ProposalStatus.EXECUTED else ObligationActionKind.DELIVERY_FAILED
        action = ObligationAction(
            action_id=ids.new_id(ids.OBLIGATION_ACTION),
            obligation_id=obligation.obligation_id,
            seq=obligation.action_count + 1,
            kind=ledger_kind,
            occurred_at=now,
            actor_kind=ActorKind.RESEARCHER,
            actor_name=reviewer.strip(),
            channel=final_channel,
            recipient_party_id=proposal.recipient_party_id if proposal.recipient_party_id != "UNROUTED" else None,
            ref_id=proposal_id,
            note=note.strip(),
        )

        updated_obligation = obligation.model_copy(
            update={
                "status": (
                    ObligationStatus.AWAITING_RESPONSE
                    if final_status is ProposalStatus.EXECUTED
                    else obligation.status
                ),
                "escalation_count": (
                    obligation.escalation_count + 1
                    if final_status is ProposalStatus.EXECUTED and obligation.status is ObligationStatus.AWAITING_RESPONSE
                    else obligation.escalation_count
                ),
                "action_count": obligation.action_count + 1,
                "last_action_at": now,
            }
        )

        approval_action = ObligationAction(
            action_id=ids.new_id(ids.OBLIGATION_ACTION),
            obligation_id=obligation.obligation_id,
            seq=updated_obligation.action_count + 1,
            kind=ObligationActionKind.PROPOSAL_APPROVED,
            occurred_at=now,
            actor_kind=ActorKind.RESEARCHER,
            actor_name=reviewer.strip(),
            ref_id=proposal_id,
            note=note.strip(),
        )
        updated_obligation = updated_obligation.model_copy(update={"action_count": updated_obligation.action_count + 1})

        with self.repository.transaction():
            self.repository.save_proposal(decided)
            self.repository.save_approval(approval)
            self.repository.save_obligation(updated_obligation)
            self.repository.append_actions([approval_action, action])

        return decided

    # -- helpers -----------------------------------------------------------

    def _require_draft(self, proposal_id: str) -> ProposedAction:
        proposal = self.repository.get_proposal(proposal_id)
        if proposal is None:
            raise ObligationError("PROPOSAL_NOT_FOUND", f"No proposal with id '{proposal_id}'.")
        if proposal.status is not ProposalStatus.DRAFT:
            raise ObligationError("PROPOSAL_NOT_DRAFT", f"Proposal {proposal_id} is not in DRAFT.")
        return proposal

    def _require_reviewer_and_note(self, reviewer: str, note: str) -> None:
        if not reviewer.strip():
            raise ObligationError("REVIEWER_REQUIRED", "A decision must record who made it.")
        if not note.strip():
            raise ObligationError("REVIEW_NOTE_REQUIRED", "A decision must record why.")
