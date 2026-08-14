"""Persistence abstraction.

The screening service depends on this interface only. Phase 5 adds a
SupabaseRepository beside JsonRepository with no change to the engine, the
service, or the API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schema.clinical import Patient
from ..schema.result import ScreeningResult
from ..schema.trial import Trial


class RepositoryError(RuntimeError):
    """Raised when persistence fails. The API maps this to 503."""


class Repository(ABC):
    @abstractmethod
    def save_patient(self, patient: Patient) -> None: ...

    @abstractmethod
    def save_trial(self, trial: Trial) -> None: ...

    @abstractmethod
    def save_screening_result(self, result: ScreeningResult) -> None: ...

    @abstractmethod
    def get_screening_result(self, result_id: str) -> ScreeningResult | None: ...

    @abstractmethod
    def list_screening_results(self) -> list[ScreeningResult]: ...
