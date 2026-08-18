"""Investigator review — the human end of the monitoring loop.

Phase 1 ends at a screening a person has to sign off. Phase 2 ends the same
way: the protocol layer raises interventions and the risk layer explains
itself, and then a named investigator says what they decided.

The division of responsibility is the same one the rest of the system enforces:

    risk provider   -> an opinion
    protocol layer  -> the required action
    investigator    -> the decision, recorded here

Nothing in this module computes a risk level, and nothing in it can alter one.
A review is appended to the timeline, which is already the append-only audit
trail, so recording one never rewrites the cycle that prompted it. The single
side effect any action may have is placing the treatment ON_HOLD, and that goes
through `TreatmentService.set_status` rather than touching the record directly.

Storing reviews as timeline events rather than as their own collection is
deliberate: the timeline is where a reader already looks for "what happened to
this patient, in order", and a review is exactly that kind of fact.
"""

from __future__ import annotations

from datetime import datetime

from . import ids
from .errors import MonitoringError
from .treatment import TreatmentService
from ..repository.monitoring_base import MonitoringRepository
from ..schema.monitoring import InvestigatorReview
from ..schema.monitoring_enums import (
    InvestigatorAction,
    MonitoringEventType,
    TreatmentStatus,
)
from ..schema.monitoring_result import MonitoringEvent

#: Actions that change the treatment. Everything absent from this map is a
#: record-only decision, which is why acknowledging a RED cycle is honest: it
#: says "a person has seen this" and claims nothing further.
_STATUS_BY_ACTION: dict[InvestigatorAction, TreatmentStatus] = {
    InvestigatorAction.HOLD_TREATMENT: TreatmentStatus.ON_HOLD,
}


class InvestigatorReviewService:
    def __init__(
        self,
        monitoring_repository: MonitoringRepository,
        treatment_service: TreatmentService,
    ) -> None:
        self.monitoring_repository = monitoring_repository
        self.treatment_service = treatment_service

    def record(
        self,
        patient_id: str,
        action: InvestigatorAction,
        reviewer: str,
        note: str,
        now: datetime,
        cycle_id: str | None = None,
    ) -> InvestigatorReview:
        """Record a decision about a monitoring cycle.

        `cycle_id` defaults to the patient's latest cycle, because that is what
        an investigator is looking at when they act. Passing it explicitly is
        supported so a review cannot be silently attributed to a newer cycle
        that arrived while the reviewer was reading the old one.
        """
        cycle = self._require_cycle(patient_id, cycle_id)

        if not reviewer.strip():
            raise MonitoringError(
                "REVIEWER_REQUIRED",
                "An investigator review must record who made the decision.",
            )
        if not note.strip():
            raise MonitoringError(
                "REVIEW_NOTE_REQUIRED",
                "An investigator review must record why the decision was made.",
            )

        status_after = self._apply_treatment_effect(
            cycle.patient_id, cycle.trial_id, action
        )

        review = InvestigatorReview(
            review_id=ids.new_id(ids.INVESTIGATOR_REVIEW),
            patient_id=cycle.patient_id,
            trial_id=cycle.trial_id,
            cycle_id=cycle.cycle_id,
            action=action,
            reviewer=reviewer.strip(),
            note=note.strip(),
            reviewed_at=now,
            risk_level=cycle.effective_risk.level,
            treatment_status_after=status_after,
        )

        self.monitoring_repository.append_events(
            [
                MonitoringEvent(
                    event_id=ids.new_id(ids.EVENT),
                    patient_id=review.patient_id,
                    trial_id=review.trial_id,
                    occurred_at=now,
                    event_type=MonitoringEventType.INVESTIGATOR_REVIEW_RECORDED,
                    summary=(
                        f"{review.reviewer} recorded "
                        f"{action.value.replace('_', ' ').lower()} on "
                        f"{review.risk_level.value}: {review.note}"
                    ),
                    ref_id=review.review_id,
                    payload=review.model_dump(mode="json"),
                )
            ]
        )
        return review

    def list_for_patient(self, patient_id: str) -> list[InvestigatorReview]:
        """Reviews reconstructed from the timeline, oldest first."""
        return [
            InvestigatorReview.model_validate(event.payload)
            for event in self.monitoring_repository.list_events(patient_id)
            if event.event_type is MonitoringEventType.INVESTIGATOR_REVIEW_RECORDED
        ]

    # -- helpers -----------------------------------------------------------

    def _require_cycle(self, patient_id: str, cycle_id: str | None):
        if cycle_id is not None:
            cycle = self.monitoring_repository.get_cycle(cycle_id)
            if cycle is None or cycle.patient_id != patient_id:
                raise MonitoringError(
                    "CYCLE_NOT_FOUND",
                    f"No monitoring cycle '{cycle_id}' for patient '{patient_id}'.",
                )
            return cycle

        cycle = self.monitoring_repository.latest_cycle(patient_id)
        if cycle is None:
            raise MonitoringError(
                "NO_CYCLE",
                f"No monitoring cycle has been run for '{patient_id}'.",
                ["There is nothing to review until a cycle has been run."],
            )
        return cycle

    def _apply_treatment_effect(
        self, patient_id: str, trial_id: str, action: InvestigatorAction
    ) -> TreatmentStatus | None:
        status = _STATUS_BY_ACTION.get(action)
        if status is None:
            return None

        active = [
            t
            for t in self.monitoring_repository.list_treatments(
                trial_id=trial_id, patient_id=patient_id
            )
            if t.status is TreatmentStatus.ACTIVE
        ]
        if not active:
            raise MonitoringError(
                "NO_ACTIVE_TREATMENT",
                f"{patient_id} has no active treatment on {trial_id} to hold.",
            )

        return self.treatment_service.set_status(active[-1].treatment_id, status).status
