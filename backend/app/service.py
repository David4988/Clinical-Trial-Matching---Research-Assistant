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
from datetime import datetime, timezone

from .ai.disagreement import detect_disagreements
from .ai.mock_provider import MockAIProvider
from .ai.provider import AIProvider
from .engine.eligibility import evaluate_trial, rule_coverage
from .engine.status import count_statuses, derive_overall_status
from .heuristics.rules import collect_flags
from .repository.base import Repository, RepositoryError
from .repository.json_repo import JsonRepository
from .schema.clinical import Patient
from .schema.enums import OverallStatus, ReviewDecision
from .schema.result import ScreeningResult, ScreeningReview
from .schema.trial import Trial


class ReviewError(ValueError):
    """A human review was refused. Carries the Phase 1 error envelope fields."""

    def __init__(self, code: str, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


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

    # -- human review ------------------------------------------------------

    def record_review(
        self,
        result_id: str,
        decision: ReviewDecision,
        reviewer: str,
        note: str,
        now: datetime | None = None,
    ) -> ScreeningResult:
        """Attach a named human's decision to a completed screening.

        The stored result is rewritten with `review` set and *nothing else*
        touched: the rule verdicts, evidence, heuristics, AI opinions and
        overall status are carried through by `model_copy`, so a review can
        never launder itself into the deterministic record.

        Approval is refused outright on an INELIGIBLE screening. A reviewer may
        judge an ambiguous case; they may not talk the engine out of a criterion
        the patient demonstrably failed.
        """
        result = self.repository.get_screening_result(result_id)
        if result is None:
            raise ReviewError(
                "RESULT_NOT_FOUND", f"No screening result with id '{result_id}'."
            )

        if not reviewer.strip():
            raise ReviewError(
                "REVIEWER_REQUIRED",
                "A review must record who made the decision.",
                ["Supply a non-empty reviewer."],
            )
        if not note.strip():
            raise ReviewError(
                "REVIEW_NOTE_REQUIRED",
                "A review must record why the decision was made.",
                ["Supply a non-empty note."],
            )

        if (
            decision is ReviewDecision.APPROVED_FOR_PHASE_2
            and result.overall_status is OverallStatus.INELIGIBLE
        ):
            raise ReviewError(
                "APPROVAL_NOT_PERMITTED",
                f"Screening {result_id} is INELIGIBLE and cannot be approved "
                "for Phase 2.",
                [result.status_reason],
            )

        review = ScreeningReview(
            decision=decision,
            reviewer=reviewer.strip(),
            note=note.strip(),
            reviewed_status=result.overall_status,
            decided_at=now or datetime.now(timezone.utc),
        )
        reviewed = result.model_copy(update={"review": review})
        self.repository.save_screening_result(reviewed)
        return reviewed
