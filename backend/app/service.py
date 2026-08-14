"""ScreeningService — the single orchestration point.

Both POST /screen and POST /screen/pdf call `screen()`. The PDF route is only
an adapter that produces (Patient, Trial); it contains no screening logic. Any
future adapter (LLM extraction, OCR, CSV, EMR API) enters at exactly this
method.

Order is deliberate and enforces the AI boundary:
    rules -> heuristics -> AI -> disagreement -> status
The AI runs after the deterministic verdicts exist and cannot alter them.
"""

from __future__ import annotations

import uuid

from .ai.disagreement import detect_disagreements
from .ai.mock_provider import MockAIProvider
from .ai.provider import AIProvider
from .engine.eligibility import evaluate_trial, rule_coverage
from .engine.status import count_statuses, derive_overall_status
from .heuristics.rules import collect_flags
from .repository.base import Repository, RepositoryError
from .repository.json_repo import JsonRepository
from .schema.clinical import Patient
from .schema.result import ScreeningResult
from .schema.trial import Trial


class ScreeningService:
    def __init__(
        self,
        repository: Repository | None = None,
        ai_provider: AIProvider | None = None,
    ) -> None:
        self.repository = repository or JsonRepository()
        self.ai_provider = ai_provider or MockAIProvider()

    def screen(
        self, patient: Patient, trial: Trial, persist: bool = True
    ) -> ScreeningResult:
        # 1. Deterministic rules — authoritative.
        criteria_results = evaluate_trial(trial, patient)

        # 2. Heuristics — advisory, describe screening quality.
        heuristic_flags = collect_flags(patient, trial, criteria_results)

        # 3. AI — advisory, reads results but cannot write them.
        ai_analysis = self.ai_provider.analyze(patient, trial, criteria_results)

        # 4. Surface conflicts without resolving them.
        disagreements = detect_disagreements(criteria_results, ai_analysis)

        # 5. Derive the overall status deterministically.
        overall_status, reason = derive_overall_status(
            criteria_results, heuristic_flags, disagreements
        )
        passed, failed, unknown = count_statuses(criteria_results)

        result = ScreeningResult(
            result_id=f"SR-{uuid.uuid4().hex[:10]}",
            patient=patient,
            trial=trial,
            overall_status=overall_status,
            criteria_results=criteria_results,
            passed_count=passed,
            failed_count=failed,
            unknown_count=unknown,
            rule_coverage=rule_coverage(trial),
            heuristic_flags=heuristic_flags,
            ai_analysis=ai_analysis,
            disagreements=disagreements,
            status_reason=reason,
        )

        if persist:
            # A storage outage must not destroy a completed screening: report
            # the result, and let the caller see the persistence failure.
            try:
                self.repository.save_screening_result(result)
            except RepositoryError:
                raise

        return result

    def get_result(self, result_id: str) -> ScreeningResult | None:
        return self.repository.get_screening_result(result_id)

    def list_results(self) -> list[ScreeningResult]:
        return self.repository.list_screening_results()
