"""JSON-file repository for Phase 1.

One file, human-readable, inspectable mid-demo. Writes go through a temp file
and an atomic replace so an interrupted run cannot leave a truncated store
behind — the cheapest possible protection against the classic "the demo ate
its own database" failure.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .paths import data_dir
from .base import Repository, RepositoryError
from ..schema.clinical import Patient
from ..schema.result import ScreeningResult
from ..schema.trial import Trial

DEFAULT_STORE = data_dir() / "store.json"

_EMPTY: dict[str, dict[str, Any]] = {"patients": {}, "trials": {}, "results": {}}


class JsonRepository(Repository):
    def __init__(self, path: Path | str = DEFAULT_STORE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- storage primitives ------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return json.loads(json.dumps(_EMPTY))
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise RepositoryError(f"Could not read store at {self.path}: {exc}") from exc
        for key in _EMPTY:
            data.setdefault(key, {})
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        try:
            # Atomic: write beside the target, then replace in one syscall.
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".store-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, default=str)
                os.replace(tmp_name, self.path)
            except Exception:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise RepositoryError(f"Could not write store at {self.path}: {exc}") from exc

    # -- Repository --------------------------------------------------------

    def save_patient(self, patient: Patient) -> None:
        data = self._load()
        data["patients"][patient.patient_id] = patient.model_dump(mode="json")
        self._write(data)

    def save_trial(self, trial: Trial) -> None:
        data = self._load()
        data["trials"][trial.trial_id] = trial.model_dump(mode="json")
        self._write(data)

    def save_screening_result(self, result: ScreeningResult) -> None:
        data = self._load()
        data["patients"][result.patient.patient_id] = result.patient.model_dump(mode="json")
        data["trials"][result.trial.trial_id] = result.trial.model_dump(mode="json")
        data["results"][result.result_id] = result.model_dump(mode="json")
        self._write(data)

    def get_screening_result(self, result_id: str) -> ScreeningResult | None:
        raw = self._load()["results"].get(result_id)
        return ScreeningResult.model_validate(raw) if raw else None

    def list_screening_results(self) -> list[ScreeningResult]:
        results = [
            ScreeningResult.model_validate(raw)
            for raw in self._load()["results"].values()
        ]
        results.sort(key=lambda r: r.generated_at, reverse=True)
        return results
