"""Phase 2 input-side canonical models: treatment, doses, observations, AEs.

These are the *recorded facts* of monitoring — what was given to the patient and
what was measured. Nothing here is derived, and nothing here holds a judgement.
Derived types (patient state, risk, interventions, dose decisions) live in
`monitoring_result.py`.

The Phase 1 boundary rule carries over unchanged: every future ingestion adapter
(device stream, EMR feed, CSV import, the synthetic generator) must produce
exactly these types, and no downstream module may care which one produced them.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import OverallStatus
from .monitoring_enums import (
    AdverseEventSeverity,
    InvestigatorAction,
    MeasurementType,
    ObservationSource,
    RiskLevel,
    TreatmentStatus,
)


class Observation(BaseModel):
    """One measurement, at one instant, from one source.

    Frozen: an observation is a historical fact. Corrections are recorded as a
    new observation, never by editing the old one — otherwise the timeline and
    the evidence trail would silently rewrite themselves.

    Note `recorded_at` is a real `datetime`, unlike Phase 1's free-form
    `LabResult.observed_at` string. Phase 1 explicitly did no date arithmetic;
    Phase 2 cannot avoid it (staleness, trends, dose intervals), so the type
    has to carry the weight.
    """

    model_config = ConfigDict(frozen=True)

    observation_id: str
    patient_id: str
    trial_id: str
    recorded_at: datetime
    source: ObservationSource
    measurement_type: MeasurementType
    value: float
    unit: str
    # Optional quality metadata. `device_id` lets a later phase correlate a run
    # of bad readings to one faulty sensor; `quality_note` is free-form text
    # from the producing system, not something this codebase interprets.
    device_id: str | None = None
    quality_note: str | None = None


class DoseAdministration(BaseModel):
    """A single administered dose within a treatment course.

    `route` is optional and free-form rather than an enum: this prototype does
    not model a formulary, and inventing a closed route vocabulary would imply
    a clinical completeness the system does not have.
    """

    model_config = ConfigDict(frozen=True)

    dose_number: int = Field(ge=1)
    administered_at: datetime
    amount: float = Field(gt=0)
    unit: str
    route: str | None = None
    administered_by: str | None = None
    note: str | None = None


class EligibilityOverride(BaseModel):
    """A human decision to treat a patient whose screening was REVIEW_REQUIRED.

    The same technique `docs/PHASES.md` reserves for the Phase 6
    `ApprovalRecord`: the override is a distinct, required object rather than a
    boolean flag, so "who decided this, and why" cannot be omitted.

    `screening_status` records what was actually overridden, which makes the
    record self-describing on the timeline long after the screening scrolled
    out of view.
    """

    model_config = ConfigDict(frozen=True)

    approved_by: str
    reason: str
    approved_at: datetime
    screening_status: OverallStatus


class TreatmentAssignment(BaseModel):
    """A patient's enrolment onto a trial drug, and the doses given so far.

    `screening_result_id` is the Phase 1 -> Phase 2 bridge. Patient identity is
    NOT copied here: it stays in the screening store and is looked up through
    the existing `Repository.get_screening_result()`. Duplicating it would
    create two records that can disagree.
    """

    treatment_id: str
    patient_id: str
    trial_id: str
    screening_result_id: str
    drug_name: str
    course_label: str | None = None
    status: TreatmentStatus = TreatmentStatus.ACTIVE
    registered_at: datetime
    doses: list[DoseAdministration] = Field(default_factory=list)
    # Required by the registration service when the screening was
    # REVIEW_REQUIRED; absent when the screening was outright ELIGIBLE.
    override: EligibilityOverride | None = None

    @property
    def dose_count(self) -> int:
        return len(self.doses)

    @property
    def latest_dose(self) -> DoseAdministration | None:
        if not self.doses:
            return None
        return max(self.doses, key=lambda d: d.administered_at)

    @property
    def next_dose_number(self) -> int:
        return self.dose_count + 1


class InvestigatorReview(BaseModel):
    """A named investigator's decision about one monitoring cycle.

    A recorded fact, like a dose or an adverse event — which is why it lives
    here and not in `monitoring_result.py`. It is what a human did, not
    something the system derived.

    The cycle it answers is referenced by id and the risk level at the time is
    copied in, so the decision stays readable on the timeline without having to
    re-open the cycle that prompted it. Recording one changes no risk level and
    no protocol output: the cycle that produced RED still says RED afterwards.
    """

    model_config = ConfigDict(frozen=True)

    review_id: str
    patient_id: str
    trial_id: str
    cycle_id: str
    action: InvestigatorAction
    reviewer: str
    note: str
    reviewed_at: datetime
    #: The effective (post-gate) level the investigator was actually looking at.
    risk_level: RiskLevel
    #: Set only when the action changed the treatment, so a reader can tell an
    #: acknowledgement apart from a hold without inspecting the treatment.
    treatment_status_after: TreatmentStatus | None = None


class AdverseEvent(BaseModel):
    """A clinician-reported adverse event.

    Explicitly reported, never inferred from vitals. The protocol layer may
    *surface* a severe excursion as worth reviewing, but it does not get to
    write one of these — that would be inventing clinical data, which is the
    one thing Phase 1 refuses to do anywhere in the engine.
    """

    event_id: str
    patient_id: str
    trial_id: str
    term: str
    severity: AdverseEventSeverity
    onset_at: datetime
    resolved_at: datetime | None = None
    reported_by: str | None = None
    note: str | None = None

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None
