"""Extraction failures.

Carries a machine-readable code plus human-readable details so the API can
return a clean structured error and the UI can render an actionable message
instead of a stack trace.
"""

from __future__ import annotations


class ExtractionError(Exception):
    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}
