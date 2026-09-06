"""The execution boundary. `execute()` accepts an `ApprovalRecord` and
nothing else — there is no `execute(obligation)` and no `execute(proposal)`.
`docs/FINAL_IMPLEMENTATION_PLAN.md` §5.5, §8.2.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..monitoring import ids as monitoring_ids
from ..monitoring.notifications import NotificationDeliveryProvider
from ..repository.monitoring_base import MonitoringRepository
from ..schema.monitoring_enums import NotificationAudience
from ..schema.monitoring_result import Notification
from ..schema.obligation_enums import DeliveryStatus
from ..schema.obligations import ApprovalRecord, ProposalExecution, ProposedAction


class ChannelRequiresTemplateError(ValueError):
    """Raised before any provider is touched — obligation and proposal stay
    untouched, matching §16.2's structural refusal."""


class ExecutionService:
    """The only class permitted to construct a `ProposalExecution`.

    Receives an already-resolved `NotificationDeliveryProvider` from its
    caller (`obligations/proposals.py`, via `comms/factory.py`) rather than
    importing `comms/` itself — this file's only channel-aware line is the
    `requires_template` precondition check, exactly per §16.2.
    """

    def __init__(self, monitoring_repository: MonitoringRepository) -> None:
        self.monitoring_repository = monitoring_repository

    def execute(
        self,
        approval: ApprovalRecord,
        proposal: ProposedAction,
        provider: NotificationDeliveryProvider,
        now: datetime | None = None,
    ) -> ProposalExecution:
        now = now or datetime.now(timezone.utc)

        if provider.requires_template and approval.template_name is None:
            raise ChannelRequiresTemplateError(
                f"{approval.channel.value} requires an approved template; none was set."
            )

        # `provider.channel`, not `approval.channel`: `comms/factory.py`
        # downgrades an unreachable Gmail/WhatsApp to
        # `InAppNotificationProvider` (§16.2), and that provider can only
        # ever actually deliver on IN_APP. The notification records the
        # channel that really carried it; `approval.channel` (preserved on
        # the `ApprovalRecord` itself) is the separate, permanent record of
        # what the human authorised.
        notification = Notification(
            notification_id=monitoring_ids.new_id(monitoring_ids.NOTIFICATION),
            patient_id=proposal.patient_ids[0] if proposal.patient_ids else "",
            trial_id=proposal.trial_id,
            audience=NotificationAudience.CLINICIAN,
            channel=provider.channel,
            subject=approval.subject,
            body=approval.body,
            created_at=now,
            proposal_id=proposal.proposal_id,
        )

        delivered_notification, outcome = provider.deliver_with_outcome(notification, approval, now)
        self.monitoring_repository.save_notifications([delivered_notification])

        return ProposalExecution(
            executed_at=now,
            provider=outcome.provider,
            channel=provider.channel,
            notification_id=delivered_notification.notification_id,
            provider_message_id=outcome.provider_message_id,
            provider_thread_id=outcome.provider_thread_id,
            delivery_status=(DeliveryStatus.SENT if outcome.delivered else DeliveryStatus.FAILED),
            error=outcome.error,
        )
