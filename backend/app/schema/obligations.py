"""Domain model for the obligation layer.

See `docs/FINAL_IMPLEMENTATION_PLAN.md` §5. Five entities that deliberately
never collapse: `Obligation` (what needs to happen), `ObligationAction`
(append-only ledger of what happened), `ProposedAction` (what TrialGuard
proposes, own lifecycle), `ApprovalRecord` (who authorised it — the only key
that opens `execute()`), and `ResponsibleParty` (a lookup table, not a CRM).

Imports only from `schema/`, matching every other file in this package.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .clinical import Evidence
from .monitoring_enums import NotificationChannel
from .obligation_enums import (
    ActorKind,
    DeliveryStatus,
    ObligationActionKind,
    ObligationPriority,
    ObligationStatus,
    ObligationType,
    PartyRole,
    ProposalStatus,
    ProposedActionType,
    ProviderKind,
    ResolutionKind,
    ResponseIntent,
)


class ObligationResolution(BaseModel):
    """A record, not a bare enum — *who* decided this, and *why*, must never
    be omissible."""

    model_config = ConfigDict(frozen=True)

    kind: ResolutionKind
    by: str
    note: str
    at: datetime


class Obligation(BaseModel):
    obligation_id: str
    obligation_key: str

    trial_id: str
    patient_id: str
    type: ObligationType
    status: ObligationStatus
    priority: ObligationPriority

    requirement_ref: str
    requirement_text: str
    protocol_id: str
    source_ref: str
    detector_source: str
    occurrence: str = ""

    title: str
    detail: str
    evidence: list[Evidence] = Field(default_factory=list)

    first_detected_at: datetime
    last_confirmed_at: datetime
    due_at: datetime | None = None

    responsible_party_id: str | None = None
    escalation_count: int = 0
    action_count: int = 0
    last_action_at: datetime | None = None

    resolved_at: datetime | None = None
    resolution: ObligationResolution | None = None

    def is_terminal(self) -> bool:
        return self.status in (ObligationStatus.RESOLVED, ObligationStatus.DISMISSED)


class ObligationAction(BaseModel):
    """The follow-up ledger. Frozen, append-only."""

    model_config = ConfigDict(frozen=True)

    action_id: str
    obligation_id: str
    seq: int
    kind: ObligationActionKind
    occurred_at: datetime
    actor_kind: ActorKind
    actor_name: str | None = None
    channel: NotificationChannel | None = None
    recipient_party_id: str | None = None
    ref_id: str | None = None
    note: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ProposalProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_by: str
    provider_kind: ProviderKind
    model_name: str | None = None
    prompt_version: str | None = None
    latency_ms: int | None = None
    tools_called: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    degraded: bool = False
    unresolved: list[str] = Field(default_factory=list)


class ProposalDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Literal["APPROVED", "REJECTED"]
    reviewer: str
    note: str
    decided_at: datetime
    edited_subject: str | None = None
    edited_body: str | None = None


class ProposalExecution(BaseModel):
    """Frozen except `delivery_status`, which WhatsApp status callbacks
    advance later, in a different transaction than the one that created it."""

    executed_at: datetime
    provider: str
    channel: NotificationChannel
    notification_id: str | None = None
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
    delivery_status: DeliveryStatus = DeliveryStatus.UNKNOWN
    error: str | None = None


class ProposedAction(BaseModel):
    proposal_id: str
    obligation_ids: list[str]
    trial_id: str
    patient_ids: list[str]

    action_type: ProposedActionType
    status: ProposalStatus

    recipient_party_id: str
    channel: NotificationChannel

    subject: str
    body: str
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)

    template_name: str | None = None
    template_params: list[str] = Field(default_factory=list)

    provenance: ProposalProvenance
    created_at: datetime
    decision: ProposalDecision | None = None
    execution: ProposalExecution | None = None


class ApprovalRecord(BaseModel):
    """The enforcement mechanism. `execute()` accepts nothing else."""

    model_config = ConfigDict(frozen=True)

    proposal_id: str
    approved_by: str
    approved_at: datetime
    channel: NotificationChannel
    subject: str
    body: str
    template_name: str | None = None
    template_params: list[str] = Field(default_factory=list)


class ResponsibleParty(BaseModel):
    model_config = ConfigDict(frozen=True)

    party_id: str
    display_name: str
    role: PartyRole
    site_id: str | None = None
    email: str | None = None
    phone: str | None = None
    preferred_channel: NotificationChannel = NotificationChannel.IN_APP
    trial_ids: list[str] = Field(default_factory=list)


class DetectedRequirement(BaseModel):
    """Not persisted. A pure value passed between a detector and the
    reconciler."""

    type: ObligationType
    trial_id: str
    patient_id: str
    requirement_ref: str
    requirement_text: str
    protocol_id: str
    source_ref: str
    evidence: list[Evidence] = Field(default_factory=list)
    occurrence: str = ""
    due_at: datetime | None = None


class DetectionScope(BaseModel):
    trial_id: str
    patient_id: str
    source: str  # DetectorSource value


class ObligationDelta(BaseModel):
    """What `reconcile()` computed. Not persisted; consumed once by
    `obligations/service.py`."""

    created: list[Obligation] = Field(default_factory=list)
    created_actions: list[ObligationAction] = Field(default_factory=list)
    touched: list[Obligation] = Field(default_factory=list)
    touched_actions: list[ObligationAction] = Field(default_factory=list)
    auto_resolved: list[Obligation] = Field(default_factory=list)
    auto_resolved_actions: list[ObligationAction] = Field(default_factory=list)

    @property
    def all_obligations(self) -> list[Obligation]:
        return [*self.created, *self.touched, *self.auto_resolved]

    @property
    def all_actions(self) -> list[ObligationAction]:
        return [*self.created_actions, *self.touched_actions, *self.auto_resolved_actions]


class IncomingMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    channel: NotificationChannel
    provider_message_id: str
    provider_thread_id: str | None = None
    from_party_id: str | None = None
    obligation_id: str | None = None
    received_at: datetime
    body_text: str
    classification: ResponseIntent | None = None
    confidence: float | None = None


class DeliveryOutcome(BaseModel):
    """What a `NotificationDeliveryProvider` reports back after
    `deliver_with_outcome()`. Never invents a delivered=True."""

    delivered: bool
    provider: str
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
    error: str | None = None


class QueueItem(BaseModel):
    """The Work Queue read model row. Computed on read, never stored."""

    obligation_id: str
    patient_id: str
    site_id: str | None = None
    type: ObligationType
    status: ObligationStatus
    priority: ObligationPriority
    title: str
    reason: str
    due_at: datetime | None = None
    responsible_party: dict[str, str] | None = None
    age_days: int
    awaiting_days: int | None = None
    escalation_count: int
    attempt_count: int
    last_action_at: datetime | None = None
    pending_proposal_id: str | None = None
    needs_human_decision: bool
