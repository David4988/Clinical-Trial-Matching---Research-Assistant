"""Inbound Gmail/WhatsApp — matching, classification, signature
verification, and the manual `/responses` demo path. Network-free: every
Gmail/WhatsApp client call is monkeypatched."""

from __future__ import annotations

import hashlib
import hmac
import json

from app.comms import gmail_client, inbound, whatsapp_client
from app.comms.signatures import verify_signature

from .obligation_support import build_client


def _seed_obligation_with_proposal(client):
    import copy

    patient = json.load(open("fixtures/patient_incomplete.json"))
    trial = json.load(open("fixtures/trial_demo.json"))
    client.post("/screen", json={"patient": patient, "trial": trial})
    obligation_id = client.get("/obligations", params={"trial_id": "CT-001"}).json()["obligations"][0]["obligation_id"]
    proposal = client.post(f"/obligations/{obligation_id}/investigate").json()
    return obligation_id, proposal


# -- deterministic matching + classification -----------------------------------


def test_gmail_message_matches_by_thread_id(tmp_path, monkeypatch):
    client = build_client(tmp_path)
    obligation_id, proposal = _seed_obligation_with_proposal(client)
    approved = client.post(
        f"/obligations/proposals/{proposal['proposal_id']}/approve",
        json={"reviewer": "Dr. Rao", "note": "ok"},
    ).json()
    thread_id = approved["execution"]["notification_id"]  # in-app fallback: no real threadId, use a synthetic one below

    # Simulate a real Gmail-executed proposal by directly registering a
    # thread id in the obligation store, exactly as GmailProvider would have.
    ctx = client.app.state.obligations
    stored = ctx.repository.get_proposal(proposal["proposal_id"])
    updated = stored.model_copy(update={"execution": stored.execution.model_copy(update={"provider_thread_id": "th-123"})})
    ctx.repository.save_proposal(updated)

    raw_gmail_message = {
        "id": "msg-1",
        "threadId": "th-123",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "From", "value": "coordinator@site03.example.org"}],
            "body": {"data": _b64("We will provide the result shortly.")},
        },
    }
    message = inbound.process_gmail_message(raw_gmail_message, ctx.repository, ctx.service)
    assert message is not None
    assert message.obligation_id == obligation_id
    assert message.classification.value == "WILL_PROVIDE"

    ledger = client.get(f"/obligations/{obligation_id}/actions").json()
    assert "RESPONSE_RECEIVED" in [a["kind"] for a in ledger]

    # A duplicate delivery of the same message id is discarded, not re-ledgered.
    duplicate = inbound.process_gmail_message(raw_gmail_message, ctx.repository, ctx.service)
    assert duplicate is None


def test_gmail_message_with_unknown_thread_is_stored_unmatched(tmp_path):
    client = build_client(tmp_path)
    ctx = client.app.state.obligations
    raw = {
        "id": "msg-unknown",
        "threadId": "th-does-not-exist",
        "payload": {"mimeType": "text/plain", "headers": [], "body": {"data": _b64("hello")}},
    }
    message = inbound.process_gmail_message(raw, ctx.repository, ctx.service)
    assert message.obligation_id is None
    assert message.classification is None

    unmatched = ctx.repository.list_incoming_messages(unmatched=True)
    assert any(m.message_id == message.message_id for m in unmatched)


def test_whatsapp_message_matches_by_context_id(tmp_path):
    client = build_client(tmp_path)
    obligation_id, proposal = _seed_obligation_with_proposal(client)
    ctx = client.app.state.obligations
    stored = ctx.repository.get_proposal(proposal["proposal_id"])
    base_execution = stored.execution or _fake_execution()
    updated = stored.model_copy(update={"execution": base_execution.model_copy(update={"provider_message_id": "wamid.OUT1"})})
    ctx.repository.save_proposal(updated)

    raw = {"id": "wamid.IN1", "from": "+15551234567", "text": {"body": "Attached is the result."}, "context": {"id": "wamid.OUT1"}}
    message = inbound.process_whatsapp_message(raw, ctx.repository, ctx.service)
    assert message.obligation_id == obligation_id
    assert message.classification.value == "PROVIDED"


def test_whatsapp_status_updates_delivery_status(tmp_path):
    client = build_client(tmp_path)
    obligation_id, proposal = _seed_obligation_with_proposal(client)
    ctx = client.app.state.obligations
    stored = ctx.repository.get_proposal(proposal["proposal_id"])
    execution = (stored.execution or _fake_execution()).model_copy(update={"provider_message_id": "wamid.OUT2"})
    ctx.repository.save_proposal(stored.model_copy(update={"execution": execution}))

    updated = inbound.process_whatsapp_status({"id": "wamid.OUT2", "status": "delivered"}, ctx.repository)
    assert updated is True
    refreshed = ctx.repository.get_proposal(proposal["proposal_id"])
    assert refreshed.execution.delivery_status.value == "DELIVERED"


# -- signature verification (route-level) ---------------------------------------


def test_webhook_verification_handshake(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    client = build_client(tmp_path)
    ok = client.get(
        "/comms/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"},
    )
    assert ok.status_code == 200
    assert ok.text == "12345"

    bad = client.get(
        "/comms/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
    )
    assert bad.status_code == 403


def test_webhook_rejects_invalid_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret")
    client = build_client(tmp_path)
    resp = client.post(
        "/comms/whatsapp/webhook",
        content=b'{"entry": []}',
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert resp.status_code == 403


def test_webhook_accepts_valid_signature_and_returns_200_for_unmatched(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "app-secret")
    client = build_client(tmp_path)
    body = json.dumps(
        {"entry": [{"changes": [{"value": {"messages": [{"id": "wamid.X", "from": "+1555", "text": {"body": "hi"}}]}}]}]}
    ).encode()
    digest = hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    resp = client.post("/comms/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": f"sha256={digest}"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "matched": False}


# -- manual /responses demo path ------------------------------------------------


def test_record_response_endpoint_never_modifies_obligation_status(tmp_path):
    client = build_client(tmp_path)
    obligation_id, _ = _seed_obligation_with_proposal(client)
    before = client.get(f"/obligations/{obligation_id}").json()

    resp = client.post(f"/obligations/{obligation_id}/responses", json={"text": "We will provide it shortly."})
    assert resp.status_code == 201
    assert resp.json()["kind"] == "RESPONSE_RECEIVED"
    assert resp.json()["payload"]["classification"] == "WILL_PROVIDE"

    after = client.get(f"/obligations/{obligation_id}").json()
    assert after["status"] == before["status"]
    assert after["resolution"] == before["resolution"]
    assert after["evidence"] == before["evidence"]


# -- helpers ---------------------------------------------------------------------


def _b64(text: str) -> str:
    import base64

    return base64.urlsafe_b64encode(text.encode()).decode("ascii")


def _fake_execution():
    from datetime import datetime, timezone

    from app.schema.obligations import ProposalExecution

    return ProposalExecution(executed_at=datetime.now(timezone.utc), provider="in-app-mock", channel="IN_APP")
