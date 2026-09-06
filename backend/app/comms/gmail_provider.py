"""Gmail delivery provider — real send, isolated entirely to this file plus
`gmail_client.py` (`docs/FINAL_IMPLEMENTATION_PLAN.md` §16.4, §17).

`configured()` requires `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`,
`GMAIL_REFRESH_TOKEN`, `GMAIL_SENDER`. The first three come from a Google
Cloud OAuth client; the refresh token specifically requires a one-time
INTERACTIVE consent a human runs once via `scripts/gmail_oauth_setup.py` —
this application never performs that flow itself, never spawns a browser,
and never blocks a request on user consent. Missing any of the four
degrades to `comms/factory.py`'s in-app fallback, logged once, never a
crash (§16.2).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from . import gmail_client
from ..monitoring.notifications import NotificationDeliveryProvider
from ..schema.monitoring_enums import NotificationChannel
from ..schema.monitoring_result import Notification
from ..schema.obligations import ApprovalRecord, DeliveryOutcome

logger = logging.getLogger("app.comms.gmail_provider")

GMAIL_CLIENT_ID_ENV = "GMAIL_CLIENT_ID"
GMAIL_CLIENT_SECRET_ENV = "GMAIL_CLIENT_SECRET"
GMAIL_REFRESH_TOKEN_ENV = "GMAIL_REFRESH_TOKEN"
GMAIL_SENDER_ENV = "GMAIL_SENDER"

#: In-memory only, for this process's lifetime — duplicate-send protection
#: against a double-click or a retried HTTP request re-approving (which
#: cannot actually happen per the state machine, since a decided proposal is
#: never DRAFT again, but this is a second, independent guard at the one
#: point that would otherwise cost a real external message).
_sent_proposal_ids: set[str] = set()


def configured() -> bool:
    return all(
        os.environ.get(var, "").strip()
        for var in (GMAIL_CLIENT_ID_ENV, GMAIL_CLIENT_SECRET_ENV, GMAIL_REFRESH_TOKEN_ENV, GMAIL_SENDER_ENV)
    )


class GmailProvider(NotificationDeliveryProvider):
    name = "gmail"
    channel = NotificationChannel.EMAIL
    supports_freeform = True
    requires_template = False

    def deliver(self, notification: Notification, now: datetime) -> Notification:
        # No ApprovalRecord in this call shape; Gmail is only ever reached
        # through deliver_with_outcome() in the obligation flow.
        return notification

    def deliver_with_outcome(
        self, notification: Notification, approval: ApprovalRecord, now: datetime
    ) -> tuple[Notification, DeliveryOutcome]:
        if not configured():
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="GMAIL_NOT_CONFIGURED"
            )

        if not approval.recipient_email:
            # A capability failure, not a crash — the party has no email on
            # file. Degrades exactly like a missing credential: the proposal
            # is marked FAILED, the obligation is untouched, nothing is lost.
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="RECIPIENT_EMAIL_MISSING"
            )

        if approval.proposal_id in _sent_proposal_ids:
            logger.warning("Duplicate Gmail send suppressed for proposal %s.", approval.proposal_id)
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="DUPLICATE_SEND_SUPPRESSED"
            )

        client_id = os.environ[GMAIL_CLIENT_ID_ENV]
        client_secret = os.environ[GMAIL_CLIENT_SECRET_ENV]
        refresh_token = os.environ[GMAIL_REFRESH_TOKEN_ENV]
        sender = os.environ[GMAIL_SENDER_ENV]

        try:
            access_token = gmail_client.refresh_access_token(client_id, client_secret, refresh_token)
            raw = gmail_client.build_mime_message(
                sender=sender, to=approval.recipient_email, subject=approval.subject, body=approval.body
            )
            sent = gmail_client.send_message(access_token, raw)
        except gmail_client.GmailClientError as exc:
            logger.error("Gmail send failed for proposal %s: %s", approval.proposal_id, exc)
            return notification, DeliveryOutcome(delivered=False, provider=self.name, error=f"GMAIL_SEND_FAILED: {exc}")
        except Exception as exc:  # noqa: BLE001 - a provider must never raise
            logger.error("Unexpected Gmail failure for proposal %s: %s", approval.proposal_id, exc)
            return notification, DeliveryOutcome(delivered=False, provider=self.name, error=f"GMAIL_SEND_FAILED: {exc}")

        _sent_proposal_ids.add(approval.proposal_id)
        delivered_notification = notification.model_copy(update={"delivered_at": now, "delivery_provider": self.name})
        return delivered_notification, DeliveryOutcome(
            delivered=True,
            provider=self.name,
            provider_message_id=sent.get("id"),
            provider_thread_id=sent.get("threadId"),
        )
