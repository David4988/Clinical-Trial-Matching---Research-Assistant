"""The Work Queue read model. A pure function, computed on read — nothing to
invalidate, nothing to keep in sync. `docs/FINAL_IMPLEMENTATION_PLAN.md` §20.1.
"""

from __future__ import annotations

from datetime import datetime

from ..schema.obligation_enums import ProposalStatus
from ..schema.obligations import Obligation, ProposedAction, QueueItem, ResponsibleParty


def build_queue(
    obligations: list[Obligation],
    proposals: list[ProposedAction],
    parties: dict[str, ResponsibleParty],
    now: datetime,
) -> list[QueueItem]:
    pending_by_obligation: dict[str, str] = {}
    attempts_by_obligation: dict[str, int] = {}
    for proposal in proposals:
        for obligation_id in proposal.obligation_ids:
            attempts_by_obligation[obligation_id] = attempts_by_obligation.get(obligation_id, 0) + 1
            if proposal.status is ProposalStatus.DRAFT:
                pending_by_obligation[obligation_id] = proposal.proposal_id

    items: list[QueueItem] = []
    for obligation in obligations:
        party = parties.get(obligation.responsible_party_id) if obligation.responsible_party_id else None
        awaiting_days = None
        if obligation.status.value == "AWAITING_RESPONSE" and obligation.last_action_at:
            awaiting_days = (now - obligation.last_action_at).days

        items.append(
            QueueItem(
                obligation_id=obligation.obligation_id,
                patient_id=obligation.patient_id,
                site_id=party.site_id if party else None,
                type=obligation.type,
                status=obligation.status,
                priority=obligation.priority,
                title=obligation.title,
                reason=obligation.detail,
                due_at=obligation.due_at,
                responsible_party=(
                    {"party_id": party.party_id, "display_name": party.display_name}
                    if party
                    else None
                ),
                age_days=(now - obligation.first_detected_at).days,
                awaiting_days=awaiting_days,
                escalation_count=obligation.escalation_count,
                attempt_count=attempts_by_obligation.get(obligation.obligation_id, 0),
                last_action_at=obligation.last_action_at,
                pending_proposal_id=pending_by_obligation.get(obligation.obligation_id),
                needs_human_decision=obligation.obligation_id in pending_by_obligation,
            )
        )

    _priority_rank = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    items.sort(
        key=lambda i: (
            not i.needs_human_decision,
            _priority_rank.get(i.priority.value, 9),
            i.due_at or datetime.max.replace(tzinfo=now.tzinfo),
            i.age_days * -1,
        )
    )
    return items
