"""Choosing which delivery provider answers for a channel.

Mirrors `risk/factory.py` and `repository/factory.py`: never raises. A
misconfigured or absent channel credential downgrades to
`InAppNotificationProvider` with a log line — a real, tested fallback, not a
crash. `docs/FINAL_IMPLEMENTATION_PLAN.md` §16.2.
"""

from __future__ import annotations

import logging

from .gmail_provider import GmailProvider, configured as gmail_configured
from .whatsapp_provider import WhatsAppProvider, configured as whatsapp_configured
from ..monitoring.notifications import InAppNotificationProvider, NotificationDeliveryProvider
from ..schema.monitoring_enums import NotificationChannel

logger = logging.getLogger("app.comms.factory")

#: Reported by GET /health so a silently degraded deployment is visible.
_ACTIVE: dict[NotificationChannel, str] = {}


def build_delivery_provider(channel: NotificationChannel) -> NotificationDeliveryProvider:
    if channel is NotificationChannel.EMAIL:
        if gmail_configured():
            _ACTIVE[channel] = "gmail"
            return GmailProvider()
        logger.info("Gmail not configured; EMAIL falls back to in-app delivery.")
        _ACTIVE[channel] = "in-app-fallback"
        return InAppNotificationProvider()

    if channel is NotificationChannel.WHATSAPP:
        if whatsapp_configured():
            _ACTIVE[channel] = "whatsapp"
            return WhatsAppProvider()
        logger.info("WhatsApp not configured; WHATSAPP falls back to in-app delivery.")
        _ACTIVE[channel] = "in-app-fallback"
        return InAppNotificationProvider()

    _ACTIVE[channel] = "in-app"
    return InAppNotificationProvider()


def active_providers() -> dict[str, str]:
    """`GET /health`'s `delivery_providers` map. Populated lazily as
    channels are actually requested; channels never used report `in-app`,
    the always-available default."""
    return {
        NotificationChannel.IN_APP.value: _ACTIVE.get(NotificationChannel.IN_APP, "in-app"),
        NotificationChannel.EMAIL.value: _ACTIVE.get(
            NotificationChannel.EMAIL, "gmail" if gmail_configured() else "in-app-fallback"
        ),
        NotificationChannel.WHATSAPP.value: _ACTIVE.get(
            NotificationChannel.WHATSAPP, "whatsapp" if whatsapp_configured() else "in-app-fallback"
        ),
    }
