"""`X-Hub-Signature-256` verification for the WhatsApp webhook.
`docs/FINAL_IMPLEMENTATION_PLAN.md` §16.4, §18.

Verified against the RAW request body, before any JSON parsing — a byte
that changes during parsing (key ordering, whitespace) would silently break
a signature computed over the original bytes.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(app_secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """`header_value` is the literal `X-Hub-Signature-256` header, e.g.
    `"sha256=<hex digest>"`. Returns False for anything malformed, missing,
    or mismatched — never raises, so a webhook handler can turn this
    directly into a 403 without a try/except of its own."""
    if not header_value or not app_secret:
        return False
    if not header_value.startswith("sha256="):
        return False
    provided_hex = header_value[len("sha256="):]

    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # Constant-time comparison — a timing side-channel on signature
    # verification is exactly the kind of thing this check exists to prevent.
    return hmac.compare_digest(expected, provided_hex)
