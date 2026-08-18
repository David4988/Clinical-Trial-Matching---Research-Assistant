"""API request/response envelopes.

Screening responses are the canonical `ScreeningResult` itself — the API adds
no shape of its own, so the frontend consumes the same model the engine emits.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..schema.clinical import Patient
from ..schema.enums import ReviewDecision
from ..schema.trial import Trial


class ScreenRequest(BaseModel):
    """Canonical screening input. The real entry point to the system."""

    patient: Patient
    trial: Trial


class RecordReviewRequest(BaseModel):
    """A human reviewer's decision about a completed screening.

    `reviewer` and `note` are both required by the service: a decision with no
    name against it, or no stated reason, is not a review.
    """

    decision: ReviewDecision
    reviewer: str
    note: str
    now: datetime | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Every failure from this API has this shape. No stack traces escape."""

    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    phase: str
    ai_provider: str
    repository: str
