"""End-to-end channel-selection behavior through the real API: email
default, explicit researcher override, WhatsApp session vs template mode,
and the full customer-initiated WhatsApp demo flow. Network-free — Gmail/
WhatsApp client calls are monkeypatched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.comms import gmail_client, whatsapp_client

from .obligation_support import build_client

FIXTURES_PATIENT = json.load(open("fixtures/patient_incomplete.json"))
FIXTURES_TRIAL = json.load(open("fixtures/trial_demo.json"))


def _screen_and_get_obligation(client):
    client.post("/screen", json={"patient": FIXTURES_PATIENT, "trial": FIXTURES_TRIAL})
    return client.get("/obligations", params={"trial_id": "CT-001"}).json()["obligations"][0]


def test_email_is_the_default_draft_channel(tmp_path):
    # fixtures/parties.json already gives SITE-03 an email — the default
    # policy must choose EMAIL over anything WhatsApp-related.
    client = build_client(tmp_path)
    obligation = _screen_and_get_obligation(client)
    proposal = client.post(f"/obligations/{obligation['obligation_id']}/investigate").json()
    assert proposal["channel"] == "EMAIL"


def test_researcher_can_explicitly_override_channel_at_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(gmail_client, "refresh_access_token", lambda *a, **k: "token")
    monkeypatch.setattr(gmail_client, "send_message", lambda *a, **k: {"id": "m1", "threadId": "t1"})
    monkeypatch.setenv("GMAIL_CLIENT_ID", "x")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "x")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "x")
    monkeypatch.setenv("GMAIL_SENDER", "trialguard@example.org")

    client = build_client(tmp_path)
    obligation = _screen_and_get_obligation(client)
    proposal = client.post(f"/obligations/{obligation['obligation_id']}/investigate").json()
    assert proposal["channel"] == "EMAIL"  # the default

    # Give the party a phone too, then approve with an explicit override —
    # the default (EMAIL) must NOT silently win over the researcher's choice.
    ctx = client.app.state.obligations
    party = ctx.repository.get_party("SITE-03")
    ctx.repository.save_party(party.model_copy(update={"phone": "+15551234567"}))

    import app.comms.whatsapp_provider as wp

    monkeypatch.setenv("META_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setattr(whatsapp_client, "send_template_message", lambda **k: {"messages": [{"id": "wamid.1"}]})
    wp._sent_proposal_ids.clear()

    approved = client.post(
        f"/obligations/proposals/{proposal['proposal_id']}/approve",
        json={"reviewer": "Dr. Rao", "note": "explicit whatsapp override", "channel": "WHATSAPP"},
    ).json()
    assert approved["execution"]["channel"] == "WHATSAPP"
    assert approved["status"] == "EXECUTED"


def test_full_customer_initiated_whatsapp_session_demo_flow(tmp_path, monkeypatch):
    """The secondary demo path (docs/FINAL_IMPLEMENTATION_PLAN.md comms
    update): customer messages first -> session opens -> researcher
    approves a free-form reply -> WhatsApp session send -> ledger."""
    client = build_client(tmp_path)
    ctx = client.app.state.obligations

    phone = "+15559876543"
    party = ctx.repository.get_party("SITE-03")
    ctx.repository.save_party(party.model_copy(update={"phone": phone}))

    obligation = _screen_and_get_obligation(client)

    # 1-2. Customer-initiated WhatsApp message arrives, recorded as unmatched
    # (no prior outbound wamid to match against, since nothing was sent yet).
    from app.comms import inbound

    inbound.process_whatsapp_message(
        {"id": "wamid.IN0", "from": phone.lstrip("+"), "text": {"body": "Hi, I have a question about a patient."}},
        ctx.repository,
        ctx.service,
    )

    # 3. The session is now open for this phone number.
    assert ctx.repository.has_active_whatsapp_session(phone, datetime.now(timezone.utc)) is True

    # 4-5. Researcher reviews the existing obligation and approves a WhatsApp
    # response — no template needed, since a session is active.
    proposal = client.post(f"/obligations/{obligation['obligation_id']}/investigate").json()

    monkeypatch.setenv("META_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setattr(whatsapp_client, "send_session_message", lambda **k: {"messages": [{"id": "wamid.OUT1"}]})

    # 6. WhatsAppProvider sends the free-form response during the valid session.
    approved = client.post(
        f"/obligations/proposals/{proposal['proposal_id']}/approve",
        json={"reviewer": "Dr. Rao", "note": "Responding in the open session.", "channel": "WHATSAPP"},
    ).json()

    assert approved["status"] == "EXECUTED"
    assert approved["execution"]["provider"] == "whatsapp-session"
    assert approved["execution"]["provider_message_id"] == "wamid.OUT1"

    # 7. Recorded in ObligationAction.
    ledger = client.get(f"/obligations/{obligation['obligation_id']}/actions").json()
    assert "MESSAGE_SENT" in [a["kind"] for a in ledger]

    # 8. Delivery status recorded.
    assert approved["execution"]["delivery_status"] == "SENT"


def test_session_delivery_rejected_without_active_session_falls_back_to_template(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    ctx = client.app.state.obligations
    phone = "+15551112222"
    party = ctx.repository.get_party("SITE-03")
    ctx.repository.save_party(party.model_copy(update={"phone": phone}))

    obligation = _screen_and_get_obligation(client)
    proposal = client.post(f"/obligations/{obligation['obligation_id']}/investigate").json()

    monkeypatch.setenv("META_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setattr(whatsapp_client, "send_template_message", lambda **k: {"messages": [{"id": "wamid.T1"}]})

    # No inbound message was ever recorded for this phone -> no session ->
    # approve() must fall back to template mode automatically.
    approved = client.post(
        f"/obligations/proposals/{proposal['proposal_id']}/approve",
        json={"reviewer": "Dr. Rao", "note": "no session available", "channel": "WHATSAPP"},
    ).json()
    assert approved["execution"]["provider"] == "whatsapp-template"
    assert approved["status"] == "EXECUTED"
