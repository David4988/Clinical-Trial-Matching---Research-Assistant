"""Responsible-party resolution. A pure function over deterministic facts —
the LLM never constructs or selects a `ResponsibleParty`.

`docs/FINAL_IMPLEMENTATION_PLAN.md` §5.6.
"""

from __future__ import annotations

from ..schema.obligation_enums import PartyRole
from ..schema.obligations import ResponsibleParty


def resolve(
    trial_id: str,
    parties: list[ResponsibleParty],
    site_id: str | None = None,
) -> ResponsibleParty | None:
    """Prefer a party at the patient's actual site; fall back to any party
    registered for the trial. Returns `None` — a valid, expected state — if
    nothing matches; the obligation still appears in the queue, unrouted."""
    candidates = [p for p in parties if trial_id in p.trial_ids]
    if not candidates:
        return None

    if site_id:
        by_site = [p for p in candidates if p.site_id == site_id]
        if by_site:
            candidates = by_site

    coordinators = [p for p in candidates if p.role is PartyRole.SITE_COORDINATOR]
    if coordinators:
        return coordinators[0]
    return candidates[0]
