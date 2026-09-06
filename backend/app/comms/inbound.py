"""`IncomingMessage` assembly + deterministic matching, shared by Gmail
polling and the WhatsApp webhook. `docs/FINAL_IMPLEMENTATION_PLAN.md` §19.

Matching is deterministic and never the model's job (§19.3): a stored
`provider_thread_id` (Gmail) or the replied-to `provider_message_id`
(WhatsApp's `context.id`) is looked up directly against a prior proposal's
execution record. There is no fuzzy matching, no "most likely obligation",
and no model call anywhere in this file. Classification (what the reply
seems to mean) is a *separate*, deliberately deterministic, keyword-based
step below it — upgradeable to a real `AgentModelProvider` call later
without changing how a message gets matched to an obligation, which is the
part that must never become probabilistic.

Inbound text is UNTRUSTED and NEVER writes to a clinical record: the only
write this module's callers ever produce is one append-only
`ObligationAction(RESPONSE_RECEIVED)` — a ledger fact ("a reply arrived and
looked like X"), not a change to `Obligation.evidence`, `.status`, or
anything the screening engine reads.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime, timezone

from ..agent.classify import classify_response
from ..obligations.service import ObligationError, ObligationService
from ..repository.obligation_base import ObligationRepository
from ..schema.obligation_enums import ActorKind, ObligationActionKind
from ..schema.obligations import IncomingMessage, ObligationAction

logger = logging.getLogger("app.comms.inbound")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _extract_gmail_header(payload: dict, name: str) -> str | None:
    for header in payload.get("headers", []):
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def _extract_gmail_body(payload: dict) -> str:
    """Walks MIME parts for the first `text/plain` body. Returns "" rather
    than raising if the shape is unexpected — an unparseable body is stored
    as an empty, UNCLEAR-classified message, never a crash."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _b64_decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        text = _extract_gmail_body(part)
        if text:
            return text
    return ""


def _b64_decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - never let a decode error propagate
        return ""


DEFAULT_GMAIL_QUERY = "is:unread label:trialguard"


def poll_gmail(
    repository: ObligationRepository,
    obligation_service: ObligationService,
    query: str = DEFAULT_GMAIL_QUERY,
    now: datetime | None = None,
) -> dict:
    """The whole `POST /comms/gmail/poll` cycle (§19.1), isolated here so
    the route itself stays a thin HTTP adapter. Raises `GmailClientError` on
    a genuine connectivity/auth failure — the route maps that to `503`."""
    from . import gmail_client
    from .gmail_provider import (
        GMAIL_CLIENT_ID_ENV,
        GMAIL_CLIENT_SECRET_ENV,
        GMAIL_REFRESH_TOKEN_ENV,
    )
    import os

    now = now or datetime.now(timezone.utc)
    access_token = gmail_client.refresh_access_token(
        os.environ[GMAIL_CLIENT_ID_ENV], os.environ[GMAIL_CLIENT_SECRET_ENV], os.environ[GMAIL_REFRESH_TOKEN_ENV]
    )
    raw_messages = gmail_client.list_recent_messages(access_token, query=query)

    processed = [process_gmail_message(raw, repository, obligation_service, now) for raw in raw_messages]
    kept = [m for m in processed if m is not None]

    return {
        "polled_at": now,
        "query": query,
        "fetched": len(raw_messages),
        "matched": sum(1 for m in kept if m.obligation_id is not None),
        "unmatched": sum(1 for m in kept if m.obligation_id is None),
        "duplicates_skipped": len(raw_messages) - len(kept),
        "messages": kept,
    }


def process_gmail_message(
    raw_message: dict,
    repository: ObligationRepository,
    obligation_service: ObligationService,
    now: datetime | None = None,
) -> IncomingMessage | None:
    """One Gmail message resource (as returned by `gmail_client.list_recent_messages`)
    -> one stored `IncomingMessage`, with a ledger entry appended when
    matched. Returns `None` for an already-seen message (idempotent, §9.4)."""
    now = now or datetime.now(timezone.utc)
    provider_message_id = raw_message["id"]

    if repository.find_incoming_message("EMAIL", provider_message_id) is not None:
        return None  # already processed — a re-poll, not a new message

    payload = raw_message.get("payload", {})
    thread_id = raw_message.get("threadId")
    from_header = _extract_gmail_header(payload, "From") or ""
    body_text = _extract_gmail_body(payload)

    obligation_id = None
    classification = None
    confidence = None

    proposal = repository.find_proposal_by_thread_id(thread_id) if thread_id else None
    if proposal is not None and proposal.obligation_ids:
        obligation_id = proposal.obligation_ids[0]
        classification, confidence = classify_response(body_text)
        _append_response_ledger_entry(repository, obligation_service, obligation_id, classification, confidence, now)

    message = IncomingMessage(
        message_id=_new_id("IM"),
        channel="EMAIL",
        provider_message_id=provider_message_id,
        provider_thread_id=thread_id,
        from_party_id=None,  # resolved by party email lookup is a future refinement; unmatched-by-party is valid
        obligation_id=obligation_id,
        received_at=now,
        body_text=body_text,
        classification=classification,
        confidence=confidence,
    )
    repository.save_incoming_message(message)
    return message


def _append_response_ledger_entry(
    repository: ObligationRepository,
    obligation_service: ObligationService,
    obligation_id: str,
    classification: ResponseIntent,
    confidence: float,
    now: datetime,
) -> None:
    obligation = repository.get_obligation(obligation_id)
    if obligation is None:
        logger.warning("Matched obligation %s no longer exists; leaving the message unattached to a ledger entry.", obligation_id)
        return
    action = ObligationAction(
        action_id=_new_id("OA"),
        obligation_id=obligation_id,
        seq=obligation.action_count + 1,
        kind=ObligationActionKind.RESPONSE_RECEIVED,
        occurred_at=now,
        actor_kind=ActorKind.SYSTEM,
        payload={"classification": classification.value, "confidence": confidence},
    )
    try:
        obligation_service.attach_action(obligation, action)
    except ObligationError as exc:
        # A reply to a terminal obligation is a real, valid scenario (e.g.
        # dismissed before the reply arrived). The message is still stored
        # with its obligation_id set, for traceability — it just does not
        # get a ledger entry on a row that can no longer accept one.
        logger.info("Reply matched a terminal obligation %s (%s); message stored without a ledger entry.", obligation_id, exc.code)


def process_whatsapp_message(
    raw_message: dict,
    repository: ObligationRepository,
    obligation_service: ObligationService,
    now: datetime | None = None,
) -> IncomingMessage | None:
    """One `messages[]` entry from the WhatsApp webhook payload. Matching
    priority 1 (§19.3): the `context.id` a reply carries — the `wamid` of
    the outbound message it replied to — looked up against a proposal's
    stored `provider_message_id`. No fallback to sender-phone matching in
    this pass: an unmatched WhatsApp reply is stored unattached rather than
    guessed at, exactly like an unmatched Gmail reply."""
    now = now or datetime.now(timezone.utc)
    provider_message_id = raw_message.get("id")
    if not provider_message_id:
        return None

    if repository.find_incoming_message("WHATSAPP", provider_message_id) is not None:
        return None

    body_text = (raw_message.get("text") or {}).get("body", "")
    context_id = (raw_message.get("context") or {}).get("id")

    obligation_id = None
    classification = None
    confidence = None

    proposal = repository.find_proposal_by_provider_message_id(context_id) if context_id else None
    if proposal is not None and proposal.obligation_ids:
        obligation_id = proposal.obligation_ids[0]
        classification, confidence = classify_response(body_text)
        _append_response_ledger_entry(repository, obligation_service, obligation_id, classification, confidence, now)

    message = IncomingMessage(
        message_id=_new_id("IM"),
        channel="WHATSAPP",
        provider_message_id=provider_message_id,
        provider_thread_id=None,  # WhatsApp has no thread concept; context.id is the match key instead
        from_party_id=None,
        obligation_id=obligation_id,
        received_at=now,
        body_text=body_text,
        classification=classification,
        confidence=confidence,
    )
    repository.save_incoming_message(message)
    return message


def process_whatsapp_status(raw_status: dict, repository: ObligationRepository, now: datetime | None = None) -> bool:
    """One `statuses[]` entry (`sent`/`delivered`/`read`/`failed`). Updates
    the matching proposal's `ProposalExecution.delivery_status` — never the
    obligation's own status, which only ever changes through the deterministic
    lifecycle in `obligations/service.py`. Returns True if a proposal was
    matched and updated."""
    from ..schema.obligation_enums import DeliveryStatus

    wamid = raw_status.get("id")
    status_value = (raw_status.get("status") or "").upper()
    if not wamid or status_value not in DeliveryStatus.__members__:
        return False

    proposal = repository.find_proposal_by_provider_message_id(wamid)
    if proposal is None or proposal.execution is None:
        return False

    updated_execution = proposal.execution.model_copy(update={"delivery_status": DeliveryStatus[status_value]})
    updated_proposal = proposal.model_copy(update={"execution": updated_execution})
    repository.save_proposal(updated_proposal)
    return True
