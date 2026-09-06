"""Inbound communication routes. Mounted under `/comms`.
`docs/FINAL_IMPLEMENTATION_PLAN.md` §17.1 (Gmail polling), §18 (WhatsApp
webhook), §23.7-23.9.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..comms import inbound
from ..comms.gmail_client import GmailClientError
from ..comms.gmail_provider import configured as gmail_configured
from ..comms.signatures import verify_signature
from ..comms.whatsapp_provider import WHATSAPP_APP_SECRET_ENV, WHATSAPP_VERIFY_TOKEN_ENV

logger = logging.getLogger("app.api.comms_routes")

router = APIRouter(prefix="/comms", tags=["comms"])


def _obligations(request: Request):
    return getattr(request.app.state, "obligations", None)


def _fail(status: int, code: str, message: str, details: list[str] | None = None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message, "details": details or []})


@router.post("/gmail/poll")
def gmail_poll(request: Request) -> dict:
    ctx = _obligations(request)
    if ctx is None:
        _fail(503, "OBLIGATIONS_NOT_ENABLED", "The obligation layer is not wired up for this app instance.")
    if not gmail_configured():
        _fail(503, "GMAIL_NOT_CONFIGURED", "Gmail credentials are not fully configured.")
    try:
        return inbound.poll_gmail(ctx.repository, ctx.service)
    except GmailClientError as exc:
        _fail(503, "GMAIL_POLL_FAILED", str(exc))


@router.get("/whatsapp/webhook")
def whatsapp_verify(
    request: Request,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> PlainTextResponse:
    """Meta's verification handshake. Match -> 200 with the BARE
    `hub.challenge` value as plain text (Meta requires the raw value, not
    JSON). Mismatch -> 403."""
    configured_token = os.environ.get(WHATSAPP_VERIFY_TOKEN_ENV, "")
    if hub_mode == "subscribe" and configured_token and hub_verify_token == configured_token and hub_challenge:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed.")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request) -> dict:
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")
    app_secret = os.environ.get(WHATSAPP_APP_SECRET_ENV, "")

    if not verify_signature(app_secret, raw_body, signature_header):
        # Invalid or missing signature -> 403, body discarded, NOTHING written.
        logger.warning("WhatsApp webhook: signature verification failed for request from %s", request.client)
        raise HTTPException(status_code=403, detail="Invalid signature.")

    import json

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        # Signature was valid but the body is not JSON — still 200 so Meta
        # does not retry a payload that will never parse.
        return {"status": "ok", "matched": False}

    ctx = _obligations(request)
    now = datetime.now(timezone.utc)
    any_matched = False

    if ctx is not None:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for raw_message in value.get("messages", []):
                    message = inbound.process_whatsapp_message(raw_message, ctx.repository, ctx.service, now)
                    if message is not None and message.obligation_id is not None:
                        any_matched = True
                for raw_status in value.get("statuses", []):
                    if inbound.process_whatsapp_status(raw_status, ctx.repository, now):
                        any_matched = True

    # Valid signature, matched or not -> always 200. Meta retries on
    # anything else, and an unmatched message is a normal, expected outcome
    # (§19.4/§23.9), not a failure.
    return {"status": "ok", "matched": any_matched}


@router.get("/health")
def comms_health() -> dict:
    from ..comms.factory import active_providers

    return {"delivery_providers": active_providers()}
