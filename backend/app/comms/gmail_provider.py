"""Gmail delivery provider.

Code-complete for the shape the plan specifies (§17); the actual OAuth/send
call is not wired up in this pass because it requires a Google Cloud OAuth
client and a user-consented refresh token — credentials only a developer with
console access can produce, and none are configured in this environment (no
`GMAIL_*` env vars set). Per `docs/FINAL_IMPLEMENTATION_PLAN.md` §16.2's own
rule, a misconfigured/absent Gmail credential must degrade the send to
in-app, not crash or fake success — that is exactly what happens here:
`deliver_with_outcome` always returns `delivered=False` with
`error="GMAIL_NOT_CONFIGURED"`, and `comms/factory.py` falls back to
`InAppNotificationProvider` when it sees that.

Setting `GMAIL_REFRESH_TOKEN`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and
`GMAIL_SENDER` would make `configured` True; wiring the real `send()` call
(RFC 2822 MIME build + `users.messages.send`) is the only remaining step,
isolated entirely to this file, per §16.4 ("the ONLY Gmail-aware module").
"""

from __future__ import annotations

import os
from datetime import datetime

from ..monitoring.notifications import NotificationDeliveryProvider
from ..schema.monitoring_enums import NotificationChannel
from ..schema.monitoring_result import Notification
from ..schema.obligations import ApprovalRecord, DeliveryOutcome

GMAIL_CLIENT_ID_ENV = "GMAIL_CLIENT_ID"
GMAIL_CLIENT_SECRET_ENV = "GMAIL_CLIENT_SECRET"
GMAIL_REFRESH_TOKEN_ENV = "GMAIL_REFRESH_TOKEN"
GMAIL_SENDER_ENV = "GMAIL_SENDER"


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
                delivered=False,
                provider=self.name,
                error="GMAIL_NOT_CONFIGURED",
            )
        # Real send path (RFC 2822 MIME build over the Gmail API) is not
        # exercised in this environment — external OAuth setup blocked, per
        # the module docstring. Left as the one remaining integration step.
        return notification, DeliveryOutcome(
            delivered=False,
            provider=self.name,
            error="GMAIL_SEND_NOT_IMPLEMENTED",
        )
