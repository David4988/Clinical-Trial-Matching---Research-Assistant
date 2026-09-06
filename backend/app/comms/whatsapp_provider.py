"""WhatsApp Business Cloud API delivery provider.

Interface-correct stub: `requires_template = True`, `supports_freeform =
False`, and `deliver_with_outcome` refuses (never sends) when
`approval.template_name` is absent — exactly the §16.2 precondition the
obligation engine's execution boundary relies on. The real Graph API call is
not implemented in this pass because it requires a Meta Business/WhatsApp
Cloud API account, a phone number, and **Meta template approval**, none of
which can be completed from this repository or in this session — an external,
multi-day approval process (`docs/FINAL_IMPLEMENTATION_PLAN.md` §18.4).

Setting `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and
`WHATSAPP_VERIFY_TOKEN` would make `configured` True; wiring the real
`POST /messages` call with template components is the only remaining step,
isolated entirely to this file, per §16.4 ("the ONLY WhatsApp-aware module").
The model never invents a template name or its parameters — both come from
`obligations/templates.py`.
"""

from __future__ import annotations

import os
from datetime import datetime

from ..monitoring.notifications import NotificationDeliveryProvider
from ..schema.monitoring_enums import NotificationChannel
from ..schema.monitoring_result import Notification
from ..schema.obligations import ApprovalRecord, DeliveryOutcome

WHATSAPP_ACCESS_TOKEN_ENV = "WHATSAPP_ACCESS_TOKEN"
WHATSAPP_PHONE_NUMBER_ID_ENV = "WHATSAPP_PHONE_NUMBER_ID"
WHATSAPP_VERIFY_TOKEN_ENV = "WHATSAPP_VERIFY_TOKEN"


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
            # messages must use an approved template. This must be
            # unreachable in practice: execution.py checks the same
            # precondition before calling any provider (§16.2).
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="TEMPLATE_REQUIRED"
            )
        if not configured():
            return notification, DeliveryOutcome(
                delivered=False, provider=self.name, error="WHATSAPP_NOT_CONFIGURED"
            )
        # Real send (Graph API POST /messages, rendering approval.template_name
        # + approval.template_params as template components) is not exercised
        # here — blocked externally on Meta template approval, per the module
        # docstring.
        return notification, DeliveryOutcome(
            delivered=False, provider=self.name, error="WHATSAPP_SEND_NOT_IMPLEMENTED"
        )
