"""API request/response envelopes.

Screening responses are the canonical `ScreeningResult` itself — the API adds
no shape of its own, so the frontend consumes the same model the engine emits.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..schema.clinical import Patient
from ..schema.trial import Trial


class ScreenRequest(BaseModel):
    """Canonical screening input. The real entry point to the system."""

    patient: Patient
    trial: Trial


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
