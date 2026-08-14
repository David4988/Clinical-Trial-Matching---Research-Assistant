"""AI provider abstraction.

Note the signature: `analyze` receives the deterministic results as *input*
and returns an `AIAnalysis` as *output*. It is handed no mutable reference to
any CriterionResult, so no provider — mock or real — can change a rule verdict.
The boundary is enforced by the type system, not by convention.

Phase 2+ adds real providers behind this same interface. Nothing downstream
changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schema.clinical import Patient
from ..schema.result import AIAnalysis, CriterionResult
from ..schema.trial import Trial


class AIProvider(ABC):
    """Advisory analysis over an already-completed deterministic screening."""

    name: str = "abstract"

    @abstractmethod
    def analyze(
        self,
        patient: Patient,
        trial: Trial,
        criteria_results: list[CriterionResult],
    ) -> AIAnalysis:
        """Return advisory opinions. Must never raise; degrade instead."""
        raise NotImplementedError
