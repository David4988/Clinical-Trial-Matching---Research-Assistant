"""New vocabulary for the obligation layer.

Kept in its own file for the same reason `monitoring_enums.py` is separate
from `enums.py`: an existing consumer needs none of this, so it costs nothing
to isolate — and it is the single highest-probability merge conflict on a
multi-developer week to avoid a shared enum file entirely.

See `docs/FINAL_IMPLEMENTATION_PLAN.md` §5.9.
"""

from __future__ import annotations

from enum import Enum


class ObligationType(str, Enum):
    """Two, not six. A type is added when its detector ships, never before."""

    MISSING_LAB_EVIDENCE = "MISSING_LAB_EVIDENCE"
    MISSING_REQUIRED_OBSERVATION = "MISSING_REQUIRED_OBSERVATION"


class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ObligationPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ObligationActionKind(str, Enum):
    """The follow-up ledger's closed vocabulary. A new kind is a reviewed
    enum member, never a string literal at a call site."""

    DETECTED = "DETECTED"
    RECONFIRMED = "RECONFIRMED"
    PARTY_RESOLVED = "PARTY_RESOLVED"
    INVESTIGATED = "INVESTIGATED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    PROPOSAL_APPROVED = "PROPOSAL_APPROVED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    MESSAGE_SENT = "MESSAGE_SENT"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    DELIVERY_STATUS_UPDATED = "DELIVERY_STATUS_UPDATED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    REQUIREMENT_CHANGED = "REQUIREMENT_CHANGED"


class ActorKind(str, Enum):
    """What kind of actor performed a ledger action — distinct from
    `InvestigatorAction`, which answers what a human decided clinically."""

    SYSTEM = "SYSTEM"
    AGENT = "AGENT"
    RESEARCHER = "RESEARCHER"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class ProposedActionType(str, Enum):
    REQUEST_LAB_EVIDENCE = "REQUEST_LAB_EVIDENCE"
    REQUEST_REPEAT_OBSERVATION = "REQUEST_REPEAT_OBSERVATION"
    ESCALATE_TO_INVESTIGATOR = "ESCALATE_TO_INVESTIGATOR"


class PartyRole(str, Enum):
    SITE_COORDINATOR = "SITE_COORDINATOR"
    INVESTIGATOR = "INVESTIGATOR"
    LAB = "LAB"
    CLINICIAN = "CLINICIAN"


class ResolutionKind(str, Enum):
    SATISFIED = "SATISFIED"
    DISMISSED = "DISMISSED"
    SUPERSEDED = "SUPERSEDED"


class ProviderKind(str, Enum):
    TEMPLATE = "TEMPLATE"
    LOCAL = "LOCAL"
    HOSTED = "HOSTED"


class DeliveryStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    FAILED = "FAILED"


class ResponseIntent(str, Enum):
    WILL_PROVIDE = "WILL_PROVIDE"
    PROVIDED = "PROVIDED"
    DISPUTED = "DISPUTED"
    UNCLEAR = "UNCLEAR"


class DetectorSource(str, Enum):
    SCREENING = "SCREENING"
    MONITORING_OBSERVATION = "MONITORING_OBSERVATION"
