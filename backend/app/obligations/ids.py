"""Identifier generation for obligation-layer entities. Same shape as
`monitoring/ids.py`."""

from __future__ import annotations

import uuid

OBLIGATION = "OB"
OBLIGATION_ACTION = "OA"
PROPOSAL = "PA"
PARTY = "PT"
MESSAGE = "IM"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"
