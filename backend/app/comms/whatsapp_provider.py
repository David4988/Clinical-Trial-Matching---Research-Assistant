"""WhatsApp Business Cloud API delivery provider — real send.

`requires_template = True`, `supports_freeform = False`: `deliver_with_outcome`
refuses (never calls the Graph API) when `approval.template_name` is absent
— the §16.2 precondition the obligation engine's execution boundary relies
on, checked here a second time as defence in depth. The model never
invents `template_name`/`template_params`; both always come from
`obligations/templates.py`, carried on the `ApprovalRecord` untouched.

`configured()` requires `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`
(the project uses `META_ACCESS_TOKEN` as the actual env var name for the
access token — see `WHATSAPP_ACCESS_TOKEN_ENV` below for the exact name
this reads).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from . import whatsapp_client
from ..monitoring.notifications import NotificationDeliveryProvider
from ..schema.monitoring_enums import NotificationChannel
from ..schema.monitoring_result import Notification
from ..schema.obligations import ApprovalRecord, DeliveryOutcome

logger = logging.getLogger("app.comms.whatsapp_provider")

#: The project's actual configured env var for the long-lived access token.
WHATSAPP_ACCESS_TOKEN_ENV = "META_ACCESS_TOKEN"
WHATSAPP_PHONE_NUMBER_ID_ENV = "WHATSAPP_PHONE_NUMBER_ID"
#: Verification token for the inbound webhook handshake (§18) — separate
#: from the access token; set by whoever configures the Meta App dashboard.
WHATSAPP_VERIFY_TOKEN_ENV = "WHATSAPP_VERIFY_TOKEN"
WHATSAPP_APP_SECRET_ENV = "WHATSAPP_APP_SECRET"

_sent_proposal_ids: set[str] = set()


def configured() -> bool:
    return all(
        os.environ.get(var, "").strip()
        for var in (WHATSAPP_ACCESS_TOKEN_ENV, WHATSAPP_PHONE_NUMBER_ID_ENV)
    )


class WhatsAppProvider(NotificationDeliveryProvider):
    name = "whatsapp"
    channel = NotificationChannel.WHATSAPP
    supports_freeform = False
    requires_template = True

    def deliver(self, notification: Notification, now: datetime) -> Notification:
        return notification

    def deliver_with_outcome(
        self, notification: Notification, approval: ApprovalRecord, now: datetime
    ) -> tuple[Notification, DeliveryOutcome]:
        if approval.template_name is None:
            # Structural refusal — outbound business-initiated WhatsApp
            # messages must use an approved template. execution.py already
            # checks this precondition before any provider is touched
            # (§16.2); this is the provider's own defence in depth.
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="TEMPLATE_REQUIRED"
            )
        if not configured():
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="WHATSAPP_NOT_CONFIGURED"
            )
        if not approval.recipient_phone:
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="RECIPIENT_PHONE_MISSING"
            )
        if approval.proposal_id in _sent_proposal_ids:
            logger.warning("Duplicate WhatsApp send suppressed for proposal %s.", approval.proposal_id)
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="DUPLICATE_SEND_SUPPRESSED"
            )

        access_token = os.environ[WHATSAPP_ACCESS_TOKEN_ENV]
        phone_number_id = os.environ[WHATSAPP_PHONE_NUMBER_ID_ENV]

        try:
            sent = whatsapp_client.send_template_message(
                access_token=access_token,
                phone_number_id=phone_number_id,
                to=approval.recipient_phone,
                template_name=approval.template_name,
                template_params=approval.template_params,
            )
        except whatsapp_client.WhatsAppClientError as exc:
            logger.error("WhatsApp send failed for proposal %s: %s", approval.proposal_id, exc)
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error=f"WHATSAPP_SEND_FAILED: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 - a provider must never raise
            logger.error("Unexpected WhatsApp failure for proposal %s: %s", approval.proposal_id, exc)
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error=f"WHATSAPP_SEND_FAILED: {exc}"
            )

        _sent_proposal_ids.add(approval.proposal_id)
        wamid = None
        messages = sent.get("messages") or []
        if messages:
            wamid = messages[0].get("id")

        delivered_notification = notification.model_copy(update={"delivered_at": now, "delivery_provider": self.name})
        return delivered_notification, DeliveryOutcome(
            delivered=True, provider=self.name, provider_message_id=wamid
        )
