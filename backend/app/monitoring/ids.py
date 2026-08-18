"""Identifier generation for Phase 2 entities.

Same shape as the Phase 1 `SR-` result id: a short prefixed hex suffix. Prefixes
are centralised so an id is self-describing in a log line or on the timeline.
"""

from __future__ import annotations

import uuid

TREATMENT = "TX"
OBSERVATION = "OBS"
ADVERSE_EVENT = "AE"
RISK = "RA"
INTERVENTION = "IV"
NOTIFICATION = "NT"
NEXT_DOSE = "ND"
CYCLE = "CY"
EVENT = "EV"
INVESTIGATOR_REVIEW = "IR"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"
