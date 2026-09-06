"""Obligation-layer API request envelopes. Responses are the canonical
`schema/obligations.py` models themselves — same convention as
`monitoring_models.py`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from ..schema.monitoring_enums import NotificationChannel


class DismissObligationRequest(BaseModel):
    reviewer: str
    note: str
    now: datetime | None = None


class ApproveProposalRequest(BaseModel):
    reviewer: str
    note: str
    channel: NotificationChannel | None = None
    edited_subject: str | None = None
    edited_body: str | None = None
    now: datetime | None = None


class RejectProposalRequest(BaseModel):
    reviewer: str
    note: str
    now: datetime | None = None
