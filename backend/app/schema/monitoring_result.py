"""Phase 2 derived-side canonical models: state, risk, protocol actions, dose decisions.

Note the same asymmetry that encodes the AI boundary in `result.py`.

`RiskAssessment` has no field an action could be written into — no intervention,
no recommendation, no dose decision. Interventions and next-dose decisions are
produced by the deterministic protocol layer, which reads risk as *input*. There
is therefore no code path by which a risk provider — mock today, a real model
later — can order a clinical action.

`PatientState` likewise carries no risk field. Risk is computed *from* state, so
state cannot quietly come to depend on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .clinical import Evidence
from .enums import Severity
from .monitoring import AdverseEvent, Observation, TreatmentAssignment
from .monitoring_enums import (
    DataQualityCode,
    DataQualityStatus,
    InterventionAction,
    MeasurementType,
    MonitoringEventType,
    NextDoseDecision,
    NotificationAudience,
    NotificationChannel,
    RiskLevel,
    TrendDirection,
)
from ..synthetic.inference.contract import PredictiveRiskAssessment


# -- patient state ---------------------------------------------------------


class MeasurementSummary(BaseModel):
    """Baseline, current value and trend for one measurement type.

    `baseline` is the mean of the earliest window of readings, so "delta from
    baseline" means "how far has this patient moved from their own starting
    point" rather than from a population norm. A trial patient is their own
    control.
    """

    measurement_type: MeasurementType
    unit: str | None = None
    baseline: float | None = None
    current: float | None = None
    latest_at: datetime | None = None
    delta_from_baseline: float | None = None
    trend: TrendDirection = TrendDirection.INSUFFICIENT_DATA
    # Change per hour from a least-squares fit over the recent window. None
    # when there are too few points for a fit to mean anything.
    slope_per_hour: float | None = None
    sample_count: int = 0
    is_stale: bool = False


class DataQualityFlag(BaseModel):
    """One observable defect in the record. Reuses Phase 1's Severity scale."""

    code: DataQualityCode
    severity: Severity
    message: str
    measurement_types: list[MeasurementType] = Field(default_factory=list)


class DataQuality(BaseModel):
    """Whether the record behind a PatientState can be relied upon.

    `is_trustworthy` is what the trust gate consults. When it is False the
    effective risk level is forced to UNKNOWN regardless of what the risk
    provider returned — a model must not be able to make a patient look safe
    on the strength of data we know is bad.
    """

    status: DataQualityStatus = DataQualityStatus.OK
    flags: list[DataQualityFlag] = Field(default_factory=list)

    @property
    def is_trustworthy(self) -> bool:
        return self.status is not DataQualityStatus.UNTRUSTWORTHY


class PatientState(BaseModel):
    """A deterministic projection of everything known about a patient at `as_of`.

    Built by a pure function from (patient, treatment, observations, adverse
    events, now). Never stored as mutable state and never incrementally
    patched: it is recomputed on read, exactly as `ScreeningResult` is computed
    fresh from its inputs. That is what keeps it reproducible and keeps
    cache-invalidation bugs out of a clinical decision path.

    Deliberately carries NO risk field.
    """

    patient_id: str
    trial_id: str
    as_of: datetime
    treatment: TreatmentAssignment | None = None
    measurements: list[MeasurementSummary] = Field(default_factory=list)
    # A bounded recent window, not the full history — enough for the timeline
    # and for a reviewer to see what the summaries were computed from.
    recent_observations: list[Observation] = Field(default_factory=list)
    active_adverse_events: list[AdverseEvent] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    observation_count: int = 0

    def measurement(self, measurement_type: MeasurementType) -> MeasurementSummary | None:
        return next(
            (m for m in self.measurements if m.measurement_type is measurement_type),
            None,
        )


# -- risk (advisory) -------------------------------------------------------


class ContributingFactor(BaseModel):
    """Why the risk layer reached its level. The explainability payload.

    Present so that "the model said RED" is never the whole answer a clinician
    is given.
    """

    factor: str
    detail: str
    weight: float = Field(ge=0.0, le=1.0)
    measurement_type: MeasurementType | None = None


class RiskAssessment(BaseModel):
    """A risk provider's advisory opinion about a patient at a point in time.

    THE BOUNDARY: this model has no action field, and must never gain one.
    A provider returns risk information; the deterministic protocol layer
    decides what to do about it. Mirrors `AIAnalysis` in Phase 1.

    `degraded` marks a provider that failed and returned an empty assessment
    rather than aborting the monitoring cycle.
    """

    assessment_id: str
    patient_id: str
    trial_id: str
    assessed_at: datetime
    level: RiskLevel
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    prediction_horizon_hours: int = Field(ge=0)
    contributing_factors: list[ContributingFactor] = Field(default_factory=list)
    # Named patterns the provider believes it recognised, in plain language.
    # Advisory prose, never parsed by the protocol layer.
    likely_patterns: list[str] = Field(default_factory=list)
    provider: str
    model_version: str
    degraded: bool = False


class EffectiveRisk(BaseModel):
    """The trust gate's output: the level the protocol layer actually acts on.

    Both levels are retained. When data quality forces UNKNOWN we keep what the
    provider said alongside the gated level and the reason, rather than
    overwriting it — the same instinct as Phase 1 surfacing a `Disagreement`
    instead of silently resolving one.
    """

    level: RiskLevel
    provider_level: RiskLevel
    gated: bool = False
    reason: str = ""


class RiskTransition(BaseModel):
    """A change in effective risk level between two consecutive cycles."""

    patient_id: str
    trial_id: str
    from_level: RiskLevel | None = None  # None on the first ever assessment
    to_level: RiskLevel
    occurred_at: datetime
    trigger: str = ""


# -- protocol output (deterministic) ---------------------------------------


class Intervention(BaseModel):
    """A protocol-mandated action. Produced only by the deterministic layer.

    `protocol_rule_id` names the demo protocol rule that fired, so every action
    traces back to a written rule rather than to a model's opinion.
    """

    intervention_id: str
    patient_id: str
    trial_id: str
    raised_at: datetime
    action: InterventionAction
    severity: Severity
    rationale: str
    protocol_rule_id: str
    risk_level: RiskLevel
    # Set when the action changes monitoring cadence; None for actions that do
    # not (a notification does not alter how often the patient is measured).
    monitoring_interval_minutes: int | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class Notification(BaseModel):
    """A generated message. Generation is separate from delivery.

    Creating one of these does not send anything. `delivered_at` and
    `delivery_provider` stay null until a delivery provider handles it, so real
    email/SMS/push can be added later without changing what generates messages.
    """

    notification_id: str
    patient_id: str
    trial_id: str
    audience: NotificationAudience
    channel: NotificationChannel
    subject: str
    body: str
    created_at: datetime
    intervention_id: str | None = None
    delivered_at: datetime | None = None
    delivery_provider: str | None = None

    @property
    def is_delivered(self) -> bool:
        return self.delivered_at is not None


# -- next dose (decision support) ------------------------------------------


class NextDoseCriterion(BaseModel):
    """One protocol check and how it came out.

    `satisfied` is deliberately three-valued. None means the criterion could
    not be evaluated, which is the Phase 1 UNKNOWN philosophy applied to dosing:
    an unevaluable safety check is never quietly counted as passed.
    """

    criterion_id: str
    description: str
    satisfied: bool | None
    detail: str = ""


class NextDoseAssessment(BaseModel):
    """Readiness for the next dose. Decision support only.

    `decision_support_only` is a literal field rather than a comment so the flag
    travels with the payload into the API and the UI. Nothing in this system
    administers a dose.
    """

    assessment_id: str
    patient_id: str
    trial_id: str
    treatment_id: str
    assessed_at: datetime
    decision: NextDoseDecision
    proposed_dose_number: int | None = None
    criteria: list[NextDoseCriterion] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    blocking_criteria: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    data_quality_status: DataQualityStatus = DataQualityStatus.OK
    decision_support_only: bool = True


# -- timeline and cycle ----------------------------------------------------


class MonitoringEvent(BaseModel):
    """An append-only timeline entry.

    Frozen, because the timeline is the audit trail: entries accumulate and are
    never rewritten. `ref_id` points at the entity the event describes, and
    `payload` carries a small JSON-safe summary so the timeline renders without
    re-joining every collection.
    """

    model_config = ConfigDict(frozen=True)

    event_id: str
    patient_id: str
    trial_id: str
    occurred_at: datetime
    event_type: MonitoringEventType
    summary: str
    ref_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RejectedObservation(BaseModel):
    """An observation refused at the boundary, with the reason.

    Rejected rows are reported back, never silently dropped: a caller must be
    able to see that its sensor is sending nonsense.
    """

    observation: Observation
    reason: str


class IngestionResult(BaseModel):
    """Outcome of one ingest batch."""

    accepted_count: int = 0
    rejected: list[RejectedObservation] = Field(default_factory=list)
    patient_ids: list[str] = Field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


class MonitoringCycleResult(BaseModel):
    """One complete pass of the monitoring loop — the `ScreeningResult` analogue.

    Carries the state it was computed from, the raw risk, the gated risk, any
    transition, the interventions and notifications produced, and the dose
    decision. One object, so a decision and its inputs cannot be separated.
    """

    model_config = ConfigDict(populate_by_name=True)

    cycle_id: str
    patient_id: str
    trial_id: str
    generated_at: datetime
    state: PatientState
    risk: RiskAssessment
    effective_risk: EffectiveRisk
    transition: RiskTransition | None = None
    interventions: list[Intervention] = Field(default_factory=list)
    notifications: list[Notification] = Field(default_factory=list)
    next_dose: NextDoseAssessment | None = None
    # Why the cycle came out the way it did, in the protocol's own words.
    summary: str = ""
    early_warning: PredictiveRiskAssessment | None = None
