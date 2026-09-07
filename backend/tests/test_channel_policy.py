"""`obligations/channel_policy.py::resolve_channel` — the "email is
primary" default-channel policy. Pure function, no I/O."""

from __future__ import annotations

from app.obligations.channel_policy import resolve_channel
from app.schema.monitoring_enums import NotificationChannel
from app.schema.obligation_enums import PartyRole
from app.schema.obligations import ResponsibleParty


def _party(email=None, phone=None) -> ResponsibleParty:
    return ResponsibleParty(
        party_id="PT-1",
        display_name="Test Party",
        role=PartyRole.SITE_COORDINATOR,
        email=email,
        phone=phone,
        trial_ids=["CT-001"],
    )


def test_email_wins_when_party_has_email():
    party = _party(email="coordinator@example.org", phone="+15551234567")
    assert resolve_channel(party, has_active_whatsapp_session=True, whatsapp_template_available=True) is NotificationChannel.EMAIL


def test_email_wins_over_whatsapp_even_without_any_whatsapp_capability():
    party = _party(email="coordinator@example.org")
    assert resolve_channel(party, has_active_whatsapp_session=False, whatsapp_template_available=False) is NotificationChannel.EMAIL


def test_active_session_wins_when_no_email():
    party = _party(phone="+15551234567")
    assert resolve_channel(party, has_active_whatsapp_session=True, whatsapp_template_available=False) is NotificationChannel.WHATSAPP


def test_template_available_wins_when_no_email_and_no_session():
    party = _party(phone="+15551234567")
    assert resolve_channel(party, has_active_whatsapp_session=False, whatsapp_template_available=True) is NotificationChannel.WHATSAPP


def test_falls_back_to_in_app_when_nothing_available():
    party = _party(phone="+15551234567")
    assert resolve_channel(party, has_active_whatsapp_session=False, whatsapp_template_available=False) is NotificationChannel.IN_APP


def test_falls_back_to_in_app_when_party_has_no_contact_info():
    party = _party()
    assert resolve_channel(party, has_active_whatsapp_session=True, whatsapp_template_available=True) is NotificationChannel.IN_APP


def test_falls_back_to_in_app_when_party_is_none():
    assert resolve_channel(None, has_active_whatsapp_session=True, whatsapp_template_available=True) is NotificationChannel.IN_APP
