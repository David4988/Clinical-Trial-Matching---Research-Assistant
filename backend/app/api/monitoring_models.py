"""Phase 2 API request envelopes.

Responses are the canonical monitoring models themselves — the API adds no
shape of its own, exactly as Phase 1 returns a bare `ScreeningResult`.

Requests exist only where the client genuinely holds less than the model does:
the server assigns identifiers, and `now` is optional so a demo can replay a
fixed timeline while normal use just takes the server clock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..schema.monitoring_enums import (
    AdverseEventSeverity,
    InvestigatorAction,
    MeasurementType,
    ObservationSource,
)
from ..synthetic.generator import Trajectory


class RegisterTreatmentRequest(BaseModel):
    """Register a screened patient onto a trial drug.

    `override_by` and `override_reason` are required when the screening was
    REVIEW_REQUIRED, and ignored when it was ELIGIBLE.
    """

    screening_result_id: str
    drug_name: str
    course_label: str | None = None
    override_by: str | None = None
    override_reason: str | None = None
    now: datetime | None = None


class RecordDoseRequest(BaseModel):
    amount: float = Field(gt=0)
    unit: str
    route: str | None = None
    administered_by: str | None = None
    note: str | None = None
    now: datetime | None = None


class RecordInvestigatorReviewRequest(BaseModel):
    """An investigator's decision about a monitoring cycle.

    `cycle_id` is optional and defaults to the patient's latest cycle. Send it
    explicitly when the reviewer was looking at a specific cycle, so a decision
    cannot be attributed to a newer one that arrived while they were reading.
    """

    action: InvestigatorAction
    reviewer: str
    note: str
    cycle_id: str | None = None
    now: datetime | None = None


class AdvanceMonitoringRequest(BaseModel):
    """Play one window of synthetic observations for one enrolled participant.

    The single-participant counterpart to `/demo/seed`, which populates the whole
    cohort. Both run the same real pipeline — ingest, then a monitoring cycle —
    so a participant advanced this way is not on a special code path.

    The window set is generated deterministically from `seed`, and `window_index`
    selects which one to play, so a demo advances one step per click and replays
    identically every time.
    """

    trial_id: str
    trajectory: Trajectory = Trajectory.GRADUAL_DETERIORATION
    window_index: int = Field(default=0, ge=0)
    windows: int = Field(default=5, ge=1, le=20)
    hours: float = 8.0
    interval_minutes: int = 15
    seed: int = 42
    #: Defaults to the treatment's registration time, so the generated timeline
    #: starts when the participant actually entered Phase 2.
    start: datetime | None = None


class ObservationInput(BaseModel):
    """One measurement. The server assigns the observation id."""

    patient_id: str
    trial_id: str
    recorded_at: datetime
    measurement_type: MeasurementType
    value: float
    unit: str
    source: ObservationSource = ObservationSource.MANUAL_ENTRY
    device_id: str | None = None
    quality_note: str | None = None


class IngestObservationsRequest(BaseModel):
    """A batch. Batches are the only shape — see MonitoringRepository."""

    observations: list[ObservationInput] = Field(min_length=1)
    now: datetime | None = None


class RecordAdverseEventRequest(BaseModel):
    patient_id: str
    trial_id: str
    term: str
    severity: AdverseEventSeverity
    onset_at: datetime | None = None
    resolved_at: datetime | None = None
    reported_by: str | None = None
    note: str | None = None


class RunCycleRequest(BaseModel):
    trial_id: str
    now: datetime | None = None


class SeedDemoRequest(BaseModel):
    """Populate the demo cohort. Development and demonstration only."""

    trial_id: str = "CT-001"
    hours: float = 8.0
    interval_minutes: int = 15
    windows: int = 5
    seed: int = 42
    start: datetime | None = None
    #: Which risk provider runs the seeded cycles. None keeps whatever the
    #: application was started with. "synthetic" replays the precomputed
    #: research fixtures; "synthetic_ml" performs live Isolation Forest
    #: inference on the generated windows. They are different things and are
    #: named differently on purpose.
    risk_provider: Literal["mock", "synthetic", "synthetic_ml"] | None = None
    #: Deprecated alias for `risk_provider="synthetic"`, kept so existing demo
    #: clients keep the behaviour they already had. Ignored when
    #: `risk_provider` is given.
    use_synthetic_ml: bool = False
