"""WhatsApp provider + client + signature verification — network-free."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.comms import signatures, whatsapp_client
from app.comms.whatsapp_provider import WhatsAppProvider, _sent_proposal_ids
from app.schema.monitoring_enums import NotificationAudience, NotificationChannel
from app.schema.monitoring_result import Notification
from app.schema.obligations import ApprovalRecord

NOW = datetime.now(timezone.utc)
ENV = {"META_ACCESS_TOKEN": "token", "WHATSAPP_PHONE_NUMBER_ID": "123456"}


@pytest.fixture(autouse=True)
def _configured_env(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    _sent_proposal_ids.clear()
    yield
    _sent_proposal_ids.clear()


def _notification() -> Notification:
    return Notification(
        notification_id="NT-1",
        patient_id="P-3311",
        trial_id="CT-001",
        audience=NotificationAudience.CLINICIAN,
        channel=NotificationChannel.WHATSAPP,
        subject="s",
        body="b",
        created_at=NOW,
    )


def _approval(
    template_name: str | None = "trialguard_evidence_request",
    recipient_phone: str | None = "+15551234567",
    session_active: bool = False,
) -> ApprovalRecord:
    return ApprovalRecord(
        proposal_id="PA-1",
        approved_by="Dr. Rao",
        approved_at=NOW,
        channel=NotificationChannel.WHATSAPP,
        subject="s",
        body="b",
        template_name=template_name,
        template_params=["P-3311", "INC-04", "CT-001"] if template_name else [],
        recipient_phone=recipient_phone,
        session_active=session_active,
    )


# -- signatures ----------------------------------------------------------------


def test_valid_signature_verifies():
    body = b'{"hello": "world"}'
    secret = "app-secret"
    import hashlib
    import hmac

    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert signatures.verify_signature(secret, body, f"sha256={digest}") is True


def test_invalid_signature_fails():
    assert signatures.verify_signature("app-secret", b"body", "sha256=deadbeef") is False


def test_missing_signature_fails():
    assert signatures.verify_signature("app-secret", b"body", None) is False


def test_malformed_signature_header_fails():
    assert signatures.verify_signature("app-secret", b"body", "not-sha256-prefixed") is False


def test_tampered_body_fails():
    import hashlib
    import hmac

    secret = "app-secret"
    digest = hmac.new(secret.encode(), b"original body", hashlib.sha256).hexdigest()
    assert signatures.verify_signature(secret, b"tampered body", f"sha256={digest}") is False


# -- whatsapp_client -------------------------------------------------------------


def test_send_template_message_success(monkeypatch):
    monkeypatch.setattr(
        "app.comms.whatsapp_client.httpx.post",
        lambda url, headers, json, timeout: httpx.Response(
            200, json={"messages": [{"id": "wamid.abc"}]}, request=httpx.Request("POST", url)
        ),
    )
    result = whatsapp_client.send_template_message("token", "phone-id", "+1555", "trialguard_evidence_request", ["a", "b"])
    assert result["messages"][0]["id"] == "wamid.abc"


def test_send_template_message_failure_raises(monkeypatch):
    monkeypatch.setattr(
        "app.comms.whatsapp_client.httpx.post",
        lambda url, headers, json, timeout: httpx.Response(
            400, json={"error": "bad template"}, request=httpx.Request("POST", url)
        ),
    )
    with pytest.raises(whatsapp_client.WhatsAppClientError):
        whatsapp_client.send_template_message("token", "phone-id", "+1555", "nonexistent_template", [])


def test_template_message_payload_has_no_freeform_text_field(monkeypatch):
    # Structural: the payload's `type` is always "template"; there is no
    # code path that builds a `{"type": "text", "text": {...}}` top-level
    # message — only named parameters inside the approved template's body.
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(json)
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.comms.whatsapp_client.httpx.post", fake_post)
    whatsapp_client.send_template_message("token", "phone-id", "+1555", "trialguard_evidence_request", ["a"])
    assert captured["type"] == "template"
    assert "text" not in captured


# -- WhatsAppProvider -----------------------------------------------------------


def test_refuses_without_template_before_any_request(monkeypatch):
    called = False

    def fail_if_called(*a, **k):
        nonlocal called
        called = True

    monkeypatch.setattr(whatsapp_client, "send_template_message", fail_if_called)
    provider = WhatsAppProvider()
    _, outcome = provider.deliver_with_outcome(_notification(), _approval(template_name=None), NOW)
    assert outcome.delivered is False
    assert outcome.error == "TEMPLATE_OR_SESSION_REQUIRED"
    assert called is False


def test_not_configured_degrades_safely(monkeypatch):
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    provider = WhatsAppProvider()
    _, outcome = provider.deliver_with_outcome(_notification(), _approval(), NOW)
    assert outcome.delivered is False
    assert outcome.error == "WHATSAPP_NOT_CONFIGURED"


def test_missing_recipient_phone_degrades_safely():
    provider = WhatsAppProvider()
    _, outcome = provider.deliver_with_outcome(_notification(), _approval(recipient_phone=None), NOW)
    assert outcome.delivered is False
    assert outcome.error == "RECIPIENT_PHONE_MISSING"


def test_successful_send_reports_wamid(monkeypatch):
    monkeypatch.setattr(whatsapp_client, "send_template_message", lambda **k: {"messages": [{"id": "wamid.xyz"}]})
    provider = WhatsAppProvider()
    notification, outcome = provider.deliver_with_outcome(_notification(), _approval(), NOW)
    assert outcome.delivered is True
    assert outcome.provider_message_id == "wamid.xyz"
    assert notification.delivered_at == NOW


def test_send_failure_degrades_without_raising(monkeypatch):
    def fail(**k):
        raise whatsapp_client.WhatsAppClientError("HTTP 400: template not approved")

    monkeypatch.setattr(whatsapp_client, "send_template_message", fail)
    provider = WhatsAppProvider()
    _, outcome = provider.deliver_with_outcome(_notification(), _approval(), NOW)
    assert outcome.delivered is False
    assert "WHATSAPP_SEND_FAILED" in outcome.error


def test_duplicate_send_is_suppressed(monkeypatch):
    monkeypatch.setattr(whatsapp_client, "send_template_message", lambda **k: {"messages": [{"id": "wamid.1"}]})
    provider = WhatsAppProvider()
    approval = _approval()
    _, first = provider.deliver_with_outcome(_notification(), approval, NOW)
    assert first.delivered is True
    _, second = provider.deliver_with_outcome(_notification(), approval, NOW)
    assert second.error == "DUPLICATE_SEND_SUPPRESSED"


# -- WhatsApp SESSION mode (customer-initiated, free-form) ----------------------


def test_session_mode_rejected_when_no_active_session_before_any_request(monkeypatch):
    called = False

    def fail_if_called(*a, **k):
        nonlocal called
        called = True

    monkeypatch.setattr(whatsapp_client, "send_session_message", fail_if_called)
    provider = WhatsAppProvider()
    approval = _approval(template_name=None, session_active=False)
    _, outcome = provider.deliver_with_outcome(_notification(), approval, NOW)
    assert outcome.delivered is False
    assert outcome.error == "TEMPLATE_OR_SESSION_REQUIRED"
    assert called is False  # rejected BEFORE any API call, per the spec


def test_session_mode_sends_freeform_body_when_session_active(monkeypatch):
    captured = {}

    def fake_send_session(**kwargs):
        captured.update(kwargs)
        return {"messages": [{"id": "wamid.session1"}]}

    monkeypatch.setattr(whatsapp_client, "send_session_message", fake_send_session)
    provider = WhatsAppProvider()
    approval = _approval(template_name=None, session_active=True)
    notification, outcome = provider.deliver_with_outcome(_notification(), approval, NOW)

    assert outcome.delivered is True
    assert outcome.provider_message_id == "wamid.session1"
    assert outcome.provider == "whatsapp-session"
    assert captured["body"] == approval.body
    assert notification.delivery_provider == "whatsapp-session"


def test_session_mode_failure_degrades_without_raising(monkeypatch):
    def fail(**k):
        raise whatsapp_client.WhatsAppClientError("HTTP 470: message outside allowed window")

    monkeypatch.setattr(whatsapp_client, "send_session_message", fail)
    provider = WhatsAppProvider()
    approval = _approval(template_name=None, session_active=True)
    _, outcome = provider.deliver_with_outcome(_notification(), approval, NOW)
    assert outcome.delivered is False
    assert "WHATSAPP_SEND_FAILED" in outcome.error


def test_template_mode_is_used_even_with_an_active_session_if_template_name_is_set(monkeypatch):
    # An explicit template_name always means template mode — session_active
    # only matters when template_name is absent.
    monkeypatch.setattr(whatsapp_client, "send_template_message", lambda **k: {"messages": [{"id": "wamid.t1"}]})
    provider = WhatsAppProvider()
    approval = _approval(template_name="trialguard_evidence_request", session_active=True)
    _, outcome = provider.deliver_with_outcome(_notification(), approval, NOW)
    assert outcome.provider == "whatsapp-template"


def test_send_session_message_payload_is_freeform_text(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(json)
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.comms.whatsapp_client.httpx.post", fake_post)
    whatsapp_client.send_session_message("token", "phone-id", "+1555", "Thanks, will do.")
    assert captured["type"] == "text"
    assert captured["text"]["body"] == "Thanks, will do."
