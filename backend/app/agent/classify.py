"""Inbound classification — no writes (§12.2, §12.5). Returns a value
object; holds no repository handle. The only write resulting from any
inbound message is one append-only `ObligationAction`, appended by the
caller (`comms/inbound.py`, or `api/obligation_routes.py`'s manual
`/responses` path), never here.

Deterministic and keyword-based for this pass — the template floor for
classification, same instinct as `obligations/templates.py` for drafting.
Lives in `agent/` (not `comms/`) specifically so both `comms/inbound.py`
and the API layer can call it without `obligations/` or `comms/` importing
each other, which the module boundary forbids.
"""

from __future__ import annotations

from ..schema.obligation_enums import ResponseIntent

_WILL_PROVIDE_KEYWORDS = ("will provide", "will send", "shortly", "soon", "working on it", "by tomorrow", "next week")
_PROVIDED_KEYWORDS = ("attached", "here is", "please find", "uploaded", "result is", "already provided", "sent it")
_DISPUTED_KEYWORDS = ("disput", "incorrect", "that's wrong", "not accurate", "mistake", "error in")


def classify_response(text: str) -> tuple[ResponseIntent, float]:
    lowered = text.lower()
    if any(k in lowered for k in _DISPUTED_KEYWORDS):
        return ResponseIntent.DISPUTED, 0.7
    if any(k in lowered for k in _PROVIDED_KEYWORDS):
        return ResponseIntent.PROVIDED, 0.7
    if any(k in lowered for k in _WILL_PROVIDE_KEYWORDS):
        return ResponseIntent.WILL_PROVIDE, 0.6
    return ResponseIntent.UNCLEAR, 0.3
