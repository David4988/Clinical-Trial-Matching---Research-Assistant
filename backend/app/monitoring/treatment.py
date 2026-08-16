"""Treatment registration — the Phase 1 -> Phase 2 doorway.

Patient identity is read from the stored `ScreeningResult` via the existing
`Repository.get_screening_result()`. It is never re-entered by the caller and
never copied into a second source of truth, so Phase 2 cannot drift from the
record Phase 1 actually screened.

The eligibility gate:

    ELIGIBLE          -> register
    REVIEW_REQUIRED   -> register ONLY with a recorded clinician override
    INELIGIBLE        -> refuse, always

REVIEW_REQUIRED is not silently promoted. It requires a named human and a
reason, both stored on the treatment and both surfaced on the timeline — the
same principle Phase 1 applies when it refuses to guess an UNKNOWN criterion.
"""

from __future__ import annotations

from datetime import datetime

from . import ids
from .errors import MonitoringError
from ..repository.base import Repository
from ..repository.monitoring_base import MonitoringRepository
from ..schema.enums import OverallStatus
from ..schema.monitoring import (
    DoseAdministration,
    EligibilityOverride,
    TreatmentAssignment,
)
from ..schema.monitoring_enums import MonitoringEventType, TreatmentStatus
from ..schema.monitoring_result import MonitoringEvent

# Statuses that may proceed at all. INELIGIBLE is absent by design.
_ALLOWED = {OverallStatus.ELIGIBLE, OverallStatus.REVIEW_REQUIRED}


class TreatmentService:
    def __init__(
        self,
        screening_repository: Repository,
        monitoring_repository: MonitoringRepository,
    ) -> None:
        self.screening_repository = screening_repository
        self.monitoring_repository = monitoring_repository

    # -- registration ------------------------------------------------------

    def register(
        self,
        screening_result_id: str,
        drug_name: str,
        now: datetime,
        course_label: str | None = None,
        override_by: str | None = None,
        override_reason: str | None = None,
    ) -> TreatmentAssignment:
        screening = self.screening_repository.get_screening_result(screening_result_id)
        if screening is None:
            raise MonitoringError(
                "SCREENING_NOT_FOUND",
                f"No screening result with id '{screening_result_id}'.",
                ["A patient must be screened in Phase 1 before treatment registration."],
            )

        status = screening.overall_status
        if status not in _ALLOWED:
            raise MonitoringError(
                "TREATMENT_NOT_PERMITTED",
                f"Screening {screening_result_id} is {status.value}; "
                "treatment cannot be registered.",
                [screening.status_reason],
            )

        override = self._build_override(status, override_by, override_reason, now)

        patient_id = screening.patient.patient_id
        trial_id = screening.trial.trial_id
        self._reject_duplicate_active_treatment(patient_id, trial_id)

        treatment = TreatmentAssignment(
            treatment_id=ids.new_id(ids.TREATMENT),
            patient_id=patient_id,
            trial_id=trial_id,
            screening_result_id=screening_result_id,
            drug_name=drug_name,
            course_label=course_label,
            status=TreatmentStatus.ACTIVE,
            registered_at=now,
            doses=[],
            override=override,
        )
        self.monitoring_repository.save_treatment(treatment)

        events = [
            self._event(
                treatment,
                now,
                MonitoringEventType.TREATMENT_REGISTERED,
                f"Registered {drug_name} for {patient_id} on {trial_id} "
                f"(screening {status.value}).",
                {"drug_name": drug_name, "screening_status": status.value},
            )
        ]
        if override is not None:
            events.append(
                self._event(
                    treatment,
                    now,
                    MonitoringEventType.ELIGIBILITY_OVERRIDE_RECORDED,
                    f"{override.approved_by} approved enrolment despite "
                    f"{status.value}: {override.reason}",
                    {"approved_by": override.approved_by, "reason": override.reason},
                )
            )
        self.monitoring_repository.append_events(events)

        return treatment

    def _build_override(
        self,
        status: OverallStatus,
        override_by: str | None,
        override_reason: str | None,
        now: datetime,
    ) -> EligibilityOverride | None:
        if status is not OverallStatus.REVIEW_REQUIRED:
            # An override on an already-ELIGIBLE screening would be noise in the
            # audit trail, so it is dropped rather than stored.
            return None

        if not (override_by and override_by.strip()) or not (
            override_reason and override_reason.strip()
        ):
            raise MonitoringError(
                "OVERRIDE_REQUIRED",
                "This screening is REVIEW_REQUIRED. Registering treatment "
                "requires a named clinician and a reason.",
                [
                    "Supply override_by and override_reason.",
                    "The override is stored on the treatment and shown on the timeline.",
                ],
            )

        return EligibilityOverride(
            approved_by=override_by.strip(),
            reason=override_reason.strip(),
            approved_at=now,
            screening_status=status,
        )

    def _reject_duplicate_active_treatment(self, patient_id: str, trial_id: str) -> None:
        existing = [
            t
            for t in self.monitoring_repository.list_treatments(
                trial_id=trial_id, patient_id=patient_id
            )
            if t.status is TreatmentStatus.ACTIVE
        ]
        if existing:
            raise MonitoringError(
                "TREATMENT_ALREADY_ACTIVE",
                f"{patient_id} already has an active treatment on {trial_id}.",
                [f"Existing treatment: {existing[0].treatment_id}."],
            )

    # -- doses -------------------------------------------------------------

    def record_dose(
        self,
        treatment_id: str,
        amount: float,
        unit: str,
        now: datetime,
        administered_by: str | None = None,
        note: str | None = None,
    ) -> TreatmentAssignment:
        treatment = self._require_treatment(treatment_id)

        if treatment.status is not TreatmentStatus.ACTIVE:
            raise MonitoringError(
                "TREATMENT_NOT_ACTIVE",
                f"Treatment {treatment_id} is {treatment.status.value}; "
                "no further doses can be recorded.",
            )

        dose = DoseAdministration(
            dose_number=treatment.next_dose_number,
            administered_at=now,
            amount=amount,
            unit=unit,
            administered_by=administered_by,
            note=note,
        )
        updated = treatment.model_copy(update={"doses": [*treatment.doses, dose]})
        self.monitoring_repository.save_treatment(updated)
        self.monitoring_repository.append_events(
            [
                self._event(
                    updated,
                    now,
                    MonitoringEventType.DOSE_ADMINISTERED,
                    f"Dose {dose.dose_number} administered: {amount} {unit}.",
                    {"dose_number": dose.dose_number, "amount": amount, "unit": unit},
                )
            ]
        )
        return updated

    def set_status(
        self, treatment_id: str, status: TreatmentStatus
    ) -> TreatmentAssignment:
        """Used by the protocol layer to place a treatment ON_HOLD, and by
        investigators to close a course. Never called by a risk provider."""
        treatment = self._require_treatment(treatment_id)
        updated = treatment.model_copy(update={"status": status})
        self.monitoring_repository.save_treatment(updated)
        return updated

    def _require_treatment(self, treatment_id: str) -> TreatmentAssignment:
        treatment = self.monitoring_repository.get_treatment(treatment_id)
        if treatment is None:
            raise MonitoringError(
                "TREATMENT_NOT_FOUND", f"No treatment with id '{treatment_id}'."
            )
        return treatment

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _event(
        treatment: TreatmentAssignment,
        now: datetime,
        event_type: MonitoringEventType,
        summary: str,
        payload: dict,
    ) -> MonitoringEvent:
        return MonitoringEvent(
            event_id=ids.new_id(ids.EVENT),
            patient_id=treatment.patient_id,
            trial_id=treatment.trial_id,
            occurred_at=now,
            event_type=event_type,
            summary=summary,
            ref_id=treatment.treatment_id,
            payload=payload,
        )
