"""Delivery provider stubs — Gmail/WhatsApp are interface-correct and
network-free by construction (§25.5, stubs only in the default suite). These
tests never touch a real network; they prove the fallback and the
template-required refusal, which are the load-bearing behaviors for the
reduced critical path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.comms.factory import build_delivery_provider
from app.comms.gmail_provider import GmailProvider
from app.comms.whatsapp_provider import WhatsAppProvider
from app.monitoring.notifications import InAppNotificationProvider
from app.schema.monitoring_enums import NotificationAudience, NotificationChannel
from app.schema.monitoring_result import Notification
from app.schema.obligations import ApprovalRecord

NOW = datetime.now(timezone.utc)


def _notification(channel: NotificationChannel) -> Notification:
    return Notification(
        notification_id="NT-1",
        patient_id="P-3311",
        trial_id="CT-001",
        audience=NotificationAudience.CLINICIAN,
        channel=channel,
        subject="s",
        body="b",
        created_at=NOW,
    )


def _approval(channel: NotificationChannel, template_name: str | None = None) -> ApprovalRecord:
    return ApprovalRecord(
        proposal_id="PA-1",
        approved_by="Dr. Rao",
        approved_at=NOW,
        channel=channel,
        subject="s",
        body="b",
        template_name=template_name,
    )


def test_factory_falls_back_to_in_app_when_gmail_not_configured(monkeypatch):
    # Hermetic regardless of what a developer's local `.env.local` happens
    # to have set — every var `configured()` checks is explicitly removed.
    for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_SENDER"):
        monkeypatch.delenv(var, raising=False)
    provider = build_delivery_provider(NotificationChannel.EMAIL)
    assert isinstance(provider, InAppNotificationProvider)


def test_factory_falls_back_to_in_app_when_whatsapp_not_configured(monkeypatch):
    for var in ("META_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"):
        monkeypatch.delenv(var, raising=False)
    provider = build_delivery_provider(NotificationChannel.WHATSAPP)
    assert isinstance(provider, InAppNotificationProvider)


def test_factory_returns_in_app_provider_for_in_app_channel():
    provider = build_delivery_provider(NotificationChannel.IN_APP)
    assert isinstance(provider, InAppNotificationProvider)


def test_gmail_provider_never_raises_when_unconfigured(monkeypatch):
    for var in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_SENDER"):
        monkeypatch.delenv(var, raising=False)
    provider = GmailProvider()
    notification, outcome = provider.deliver_with_outcome(
        _notification(NotificationChannel.EMAIL), _approval(NotificationChannel.EMAIL), NOW
    )
    assert outcome.delivered is False
    assert outcome.error == "GMAIL_NOT_CONFIGURED"


def test_whatsapp_provider_refuses_without_template():
    provider = WhatsAppProvider()
    notification, outcome = provider.deliver_with_outcome(
        _notification(NotificationChannel.WHATSAPP),
        _approval(NotificationChannel.WHATSAPP, template_name=None),
        NOW,
    )
    assert outcome.delivered is False
    assert outcome.error == "TEMPLATE_OR_SESSION_REQUIRED"


def test_whatsapp_provider_declares_template_required_capability():
    provider = WhatsAppProvider()
    # requires_template stays True: a template is required UNLESS a session
    # is active (checked via ApprovalRecord.session_active, not this flag).
    assert provider.requires_template is True
    # supports_freeform is True now — only inside an active session, which
    # this static capability flag cannot express; deliver_with_outcome is
    # the precise gate.
    assert provider.supports_freeform is True


def test_in_app_provider_delivers_only_in_app_channel():
    provider = InAppNotificationProvider()
    delivered = provider.deliver(_notification(NotificationChannel.IN_APP), NOW)
    assert delivered.delivered_at == NOW

    not_delivered = provider.deliver(_notification(NotificationChannel.EMAIL), NOW)
    assert not_delivered.delivered_at is None
