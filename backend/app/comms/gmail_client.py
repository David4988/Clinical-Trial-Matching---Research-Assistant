"""The ONLY Gmail-aware module besides `gmail_provider.py`
(`docs/FINAL_IMPLEMENTATION_PLAN.md` §16.4). OAuth refresh, MIME
construction, send, and inbound listing — plain `httpx`, no Google client
library, matching the plan's "one dependency, not a new SDK" instinct
(`LocalProvider` makes the same call with `httpx`).

Credentials: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`,
`GMAIL_SENDER`. The refresh token is obtained ONCE, interactively, by a human
running `scripts/gmail_oauth_setup.py` — never by this application, which
never spawns a browser or blocks a request on user consent.
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from email.utils import make_msgid

import httpx

logger = logging.getLogger("app.comms.gmail_client")

TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# The narrowest scope that can send mail — never read/modify the inbox, never
# manage labels beyond what listing requires for inbound polling.
SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"


class GmailClientError(RuntimeError):
    """Never leaks a raw token or secret in its message."""


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str, timeout: float = 15.0) -> str:
    """Exchanges the long-lived refresh token for a short-lived access
    token. Called once per send — Gmail access tokens expire in ~1 hour and
    this repository has no long-running process that would benefit from
    caching one across requests."""
    response = httpx.post(
        TOKEN_URI,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=timeout,
    )
    if response.status_code != 200:
        # Never echo the response body verbatim into logs at INFO/WARNING —
        # Google's error payloads do not contain the secret itself, but the
        # request that produced them did, so this stays at the caller's
        # discretion via the raised message only, never auto-logged here.
        raise GmailClientError(f"Token refresh failed: HTTP {response.status_code}")
    body = response.json()
    token = body.get("access_token")
    if not token:
        raise GmailClientError("Token refresh response had no access_token.")
    return token


def build_mime_message(sender: str, to: str, subject: str, body: str) -> str:
    """RFC 2822 MIME, base64url-encoded exactly as the Gmail API's
    `users.messages.send` requires in its `raw` field."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Message-Id"] = make_msgid()
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return raw


def send_message(access_token: str, raw_mime: str, timeout: float = 30.0) -> dict:
    """Returns `{"id": ..., "threadId": ...}` — the Gmail message id and
    thread id, exactly what `ProposalExecution.provider_message_id` /
    `.provider_thread_id` need. Raises `GmailClientError` on any non-2xx;
    the provider (never this module) decides how that becomes a
    `DeliveryOutcome`."""
    response = httpx.post(
        f"{GMAIL_API_BASE}/messages/send",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw_mime},
        timeout=timeout,
    )
    if response.status_code != 200:
        raise GmailClientError(f"Gmail send failed: HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def list_recent_messages(access_token: str, query: str, max_results: int = 10, timeout: float = 30.0) -> list[dict]:
    """The inbound polling primitive (§19.1): a plain `messages.list` +
    `messages.get` per id, read-only. Returns full message resources
    (`id`, `threadId`, `payload` with headers and body) — enough for
    `comms/inbound.py` to build an `IncomingMessage` without a second
    round-trip type."""
    list_response = httpx.get(
        f"{GMAIL_API_BASE}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"q": query, "maxResults": max_results},
        timeout=timeout,
    )
    if list_response.status_code != 200:
        raise GmailClientError(f"Gmail list failed: HTTP {list_response.status_code}")
    ids = [item["id"] for item in list_response.json().get("messages", [])]

    messages = []
    for message_id in ids:
        get_response = httpx.get(
            f"{GMAIL_API_BASE}/messages/{message_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"format": "full"},
            timeout=timeout,
        )
        if get_response.status_code == 200:
            messages.append(get_response.json())
        else:
            logger.warning("Could not fetch Gmail message %s: HTTP %s", message_id, get_response.status_code)
    return messages
