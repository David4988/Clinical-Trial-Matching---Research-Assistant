"""The ONLY WhatsApp-aware module besides `whatsapp_provider.py` and
`signatures.py` (`docs/FINAL_IMPLEMENTATION_PLAN.md` §16.4, §18). Plain
`httpx` against the Graph API — no Meta SDK.
"""

from __future__ import annotations

import httpx

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class WhatsAppClientError(RuntimeError):
    pass


def send_template_message(
    access_token: str,
    phone_number_id: str,
    to: str,
    template_name: str,
    template_params: list[str],
    language_code: str = "en_US",
    timeout: float = 30.0,
) -> dict:
    """Sends an approved-template message. Returns the Graph API response,
    which carries `messages[0].id` — the `wamid` stored as
    `ProposalExecution.provider_message_id`.

    Outbound business-initiated WhatsApp messages must use an approved
    template (§18.2); this function has no code path for free-form text —
    that constraint is structural here, not just documented.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": (
                [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": param} for param in template_params],
                    }
                ]
                if template_params
                else []
            ),
        },
    }
    response = httpx.post(
        f"{GRAPH_API_BASE}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code != 200:
        raise WhatsAppClientError(f"WhatsApp send failed: HTTP {response.status_code}: {response.text[:400]}")
    return response.json()


def send_session_message(
    access_token: str,
    phone_number_id: str,
    to: str,
    body: str,
    timeout: float = 30.0,
) -> dict:
    """Free-form text, valid ONLY inside an open customer-service window
    (Meta re-opens a 24h window on every customer-initiated message).
    Callers must check that window is open — `WhatsAppProvider` does this
    via `ApprovalRecord.session_active` — before calling this function;
    Meta itself also rejects the call outside the window (error #131047),
    so an unchecked call fails loudly either way, never silently.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    response = httpx.post(
        f"{GRAPH_API_BASE}/{phone_number_id}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json=payload,
        timeout=timeout,
    )
    if response.status_code != 200:
        raise WhatsAppClientError(f"WhatsApp session send failed: HTTP {response.status_code}: {response.text[:400]}")
    return response.json()
