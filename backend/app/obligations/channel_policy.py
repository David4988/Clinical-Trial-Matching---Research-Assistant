"""Deterministic default-channel resolution — the "email is primary" policy.

A pure function, same instinct as `rules.py::priority_for` and
`parties.resolve`: no repository handle, no I/O, no model call. The one
input that genuinely requires a repository lookup — whether a WhatsApp
session window is currently open — is resolved by the caller
(`ObligationProposalService`) and passed in as a plain fact, exactly like
`has_active_treatment` is already passed into `reconcile()`.

Policy (`docs/FINAL_IMPLEMENTATION_PLAN.md` communication-strategy update):

    1. party has an email address           -> EMAIL
    2. an active WhatsApp session is open    -> WHATSAPP (free-form/session)
    3. WhatsApp template delivery is usable  -> WHATSAPP (template)
    4. otherwise                             -> IN_APP

This only computes the *default* — the one a `ProposedAction` is drafted
with. A researcher's explicit choice at approval time (`approve(channel=...)`)
always wins and never routes back through this function.
"""

from __future__ import annotations

from ..schema.monitoring_enums import NotificationChannel
from ..schema.obligations import ResponsibleParty


def resolve_channel(
    party: ResponsibleParty | None,
    has_active_whatsapp_session: bool,
    whatsapp_template_available: bool,
) -> NotificationChannel:
    if party is None:
        return NotificationChannel.IN_APP

    if party.email:
        return NotificationChannel.EMAIL

    if party.phone and has_active_whatsapp_session:
        return NotificationChannel.WHATSAPP

    if party.phone and whatsapp_template_available:
        return NotificationChannel.WHATSAPP

    return NotificationChannel.IN_APP
