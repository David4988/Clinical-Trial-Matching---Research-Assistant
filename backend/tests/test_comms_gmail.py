"""Gmail provider + client — network-free. Every httpx call is monkeypatched."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.comms import gmail_client
from app.comms.gmail_provider import GmailProvider, _sent_proposal_ids
from app.schema.monitoring_enums import NotificationAudience, NotificationChannel
from app.schema.monitoring_result import Notification
from app.schema.obligations import ApprovalRecord

NOW = datetime.now(timezone.utc)
ENV = {
    "GMAIL_CLIENT_ID": "cid",
    "GMAIL_CLIENT_SECRET": "secret",
    "GMAIL_REFRESH_TOKEN": "refresh",
    "GMAIL_SENDER": "trialguard@example.org",
}


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
        channel=NotificationChannel.EMAIL,
        subject="s",
        body="b",
        created_at=NOW,
    )


def _approval(recipient_email: str | None = "coordinator@site03.example.org") -> ApprovalRecord:
    return ApprovalRecord(
        proposal_id="PA-1",
        approved_by="Dr. Rao",
        approved_at=NOW,
        channel=NotificationChannel.EMAIL,
        subject="Missing eGFR",
        body="Please provide the eGFR result.",
        recipient_email=recipient_email,
    )


# -- gmail_client ------------------------------------------------------------


def test_build_mime_message_is_valid_and_base64url():
    raw = gmail_client.build_mime_message("from@x.com", "to@y.com", "Subject line", "Body text")
    import base64

    decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8", errors="replace")
    assert "Subject line" in decoded
    assert "to@y.com" in decoded
    assert "Body text" in decoded


def test_refresh_access_token_success(monkeypatch):
    monkeypatch.setattr(
        "app.comms.gmail_client.httpx.post",
        lambda url, data, timeout: httpx.Response(200, json={"access_token": "abc123"}, request=httpx.Request("POST", url)),
    )
    assert gmail_client.refresh_access_token("cid", "secret", "refresh") == "abc123"


def test_refresh_access_token_failure_raises_client_error(monkeypatch):
    monkeypatch.setattr(
        "app.comms.gmail_client.httpx.post",
        lambda url, data, timeout: httpx.Response(400, json={"error": "invalid_grant"}, request=httpx.Request("POST", url)),
    )
    with pytest.raises(gmail_client.GmailClientError):
        gmail_client.refresh_access_token("cid", "secret", "bad-refresh")


def test_send_message_success(monkeypatch):
    monkeypatch.setattr(
        "app.comms.gmail_client.httpx.post",
        lambda url, headers, json, timeout: httpx.Response(
            200, json={"id": "msg123", "threadId": "thread123"}, request=httpx.Request("POST", url)
        ),
    )
    result = gmail_client.send_message("token", "raw-mime")
    assert result == {"id": "msg123", "threadId": "thread123"}


# -- GmailProvider -------------------------------------------------------------


def test_not_configured_degrades_safely(monkeypatch):
    monkeypatch.delenv("GMAIL_REFRESH_TOKEN", raising=False)
    provider = GmailProvider()
    _, outcome = provider.deliver_with_outcome(_notification(), _approval(), NOW)
    assert outcome.delivered is False
    assert outcome.error == "GMAIL_NOT_CONFIGURED"


def test_missing_recipient_email_degrades_safely():
    provider = GmailProvider()
    _, outcome = provider.deliver_with_outcome(_notification(), _approval(recipient_email=None), NOW)
    assert outcome.delivered is False
    assert outcome.error == "RECIPIENT_EMAIL_MISSING"


def test_successful_send_reports_message_and_thread_id(monkeypatch):
    monkeypatch.setattr(gmail_client, "refresh_access_token", lambda *a, **k: "token")
    monkeypatch.setattr(gmail_client, "send_message", lambda *a, **k: {"id": "msg1", "threadId": "th1"})

    provider = GmailProvider()
    notification, outcome = provider.deliver_with_outcome(_notification(), _approval(), NOW)

    assert outcome.delivered is True
    assert outcome.provider_message_id == "msg1"
    assert outcome.provider_thread_id == "th1"
    assert notification.delivered_at == NOW


def test_send_failure_degrades_without_raising(monkeypatch):
    monkeypatch.setattr(gmail_client, "refresh_access_token", lambda *a, **k: "token")

    def fail_send(*a, **k):
        raise gmail_client.GmailClientError("Gmail send failed: HTTP 500")

    monkeypatch.setattr(gmail_client, "send_message", fail_send)
    provider = GmailProvider()
    _, outcome = provider.deliver_with_outcome(_notification(), _approval(), NOW)
    assert outcome.delivered is False
    assert "GMAIL_SEND_FAILED" in outcome.error


def test_duplicate_send_is_suppressed(monkeypatch):
    monkeypatch.setattr(gmail_client, "refresh_access_token", lambda *a, **k: "token")
    monkeypatch.setattr(gmail_client, "send_message", lambda *a, **k: {"id": "msg1", "threadId": "th1"})

    provider = GmailProvider()
    approval = _approval()
    _, first = provider.deliver_with_outcome(_notification(), approval, NOW)
    assert first.delivered is True

    _, second = provider.deliver_with_outcome(_notification(), approval, NOW)
    assert second.delivered is False
    assert second.error == "DUPLICATE_SEND_SUPPRESSED"
