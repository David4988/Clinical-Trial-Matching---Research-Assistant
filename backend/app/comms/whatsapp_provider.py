"""WhatsApp Business Cloud API delivery provider — real send.

WhatsApp is the SECONDARY external channel (Gmail is primary — see
`docs/FINAL_IMPLEMENTATION_PLAN.md`'s communication-strategy update). This
provider supports two distinct delivery modes over the same transport:

- **Template** (business-initiated, outside any open session): requires an
  approved `template_name`/`template_params`, always deterministic
  (`obligations/templates.py`), never invented by a model.
- **Session** (customer-initiated, inside an open 24h window): free-form
  `subject`/`body`, only when `ApprovalRecord.session_active` is True —
  resolved deterministically by `ObligationProposalService.approve()` from
  `ObligationRepository.has_active_whatsapp_session()`, never by this
  provider reaching into a repository itself (providers stay pure).

`deliver_with_outcome` refuses (never calls the Graph API) when NEITHER a
template nor an active session is available — the §16.2 precondition the
obligation engine's execution boundary also checks; this is the provider's
own defence in depth. The model never invents `template_name`/
`template_params`, and never decides which mode is used — that is a fact
about the world (is a session open?), not a drafting choice.

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
    #: Freeform IS supported — but only inside an active session, which is
    #: a runtime fact this static flag cannot express. `deliver_with_outcome`
    #: is the actual, precise gate.
    supports_freeform = True
    #: Still True: a template is required UNLESS a session is active. See
    #: `obligations/execution.py`'s precondition, which reads this alongside
    #: `ApprovalRecord.session_active`.
    requires_template = True

    def deliver(self, notification: Notification, now: datetime) -> Notification:
        return notification

    def deliver_with_outcome(
        self, notification: Notification, approval: ApprovalRecord, now: datetime
    ) -> tuple[Notification, DeliveryOutcome]:
        session_mode = approval.template_name is None

        if session_mode and not approval.session_active:
            # Structural refusal — no template AND no open session. Reject
            # before any API call rather than let Meta's own #131047 do it.
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="TEMPLATE_OR_SESSION_REQUIRED"
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
        provider_label = "whatsapp-session" if session_mode else "whatsapp-template"

        try:
            if session_mode:
                sent = whatsapp_client.send_session_message(
                    access_token=access_token,
                    phone_number_id=phone_number_id,
                    to=approval.recipient_phone,
                    body=approval.body,
                )
            else:
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
                delivered=False, provider=provider_label, error=f"WHATSAPP_SEND_FAILED: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 - a provider must never raise
            logger.error("Unexpected WhatsApp failure for proposal %s: %s", approval.proposal_id, exc)
            return notification, DeliveryOutcome(
                delivered=False, provider=provider_label, error=f"WHATSAPP_SEND_FAILED: {exc}"
            )

        _sent_proposal_ids.add(approval.proposal_id)
        wamid = None
        messages = sent.get("messages") or []
        if messages:
            wamid = messages[0].get("id")

        delivered_notification = notification.model_copy(update={"delivered_at": now, "delivery_provider": provider_label})
        return delivered_notification, DeliveryOutcome(
            delivered=True, provider=provider_label, provider_message_id=wamid
        )
