"""Canonical enumerations for Phase 2 treatment monitoring.

Kept separate from `enums.py` so the Phase 1 contract file is not touched. The
same rule applies here as there: these names appear in API responses and in the
frontend types, so changing a *value* is a breaking contract change. Adding a
member is not.

Phase 1's `Severity` (INFO/WARN) is deliberately NOT redefined here — data
quality flags and interventions reuse it, so a reader never has to ask which
severity scale is in play.
"""

from enum import Enum


class MeasurementType(str, Enum):
    """The vital signs Phase 2 understands.

    Deliberately a closed vocabulary, for the same reason the Phase 1 rule
    vocabulary is small: an unrecognised measurement should be rejected at the
    boundary rather than silently stored as an unusable row.
    """

    HEART_RATE = "HEART_RATE"
    SYSTOLIC_BP = "SYSTOLIC_BP"
    DIASTOLIC_BP = "DIASTOLIC_BP"
    SPO2 = "SPO2"
    TEMPERATURE = "TEMPERATURE"
    RESPIRATORY_RATE = "RESPIRATORY_RATE"


class ObservationSource(str, Enum):
    """Where an observation came from.

    SYNTHETIC exists so generated demo data is self-labelling at the schema
    level. A synthetic row can never quietly read as a real clinical reading.
    """

    BEDSIDE_MONITOR = "BEDSIDE_MONITOR"
    WEARABLE = "WEARABLE"
    MANUAL_ENTRY = "MANUAL_ENTRY"
    SYNTHETIC = "SYNTHETIC"


class TreatmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    WITHDRAWN = "WITHDRAWN"


class RiskLevel(str, Enum):
    """Triage vocabulary for the risk layer.

    UNKNOWN is a first-class level, not a failure mode: it is what the trust
    gate forces when the underlying data cannot be relied upon. It must never
    be treated as "probably fine".
    """

    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"
    UNKNOWN = "UNKNOWN"


class TrendDirection(str, Enum):
    RISING = "RISING"
    FALLING = "FALLING"
    STABLE = "STABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DataQualityCode(str, Enum):
    IMPOSSIBLE_VALUE = "IMPOSSIBLE_VALUE"
    INVALID_UNIT = "INVALID_UNIT"
    MISSING_MEASUREMENT = "MISSING_MEASUREMENT"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    CONFLICTING_OBSERVATIONS = "CONFLICTING_OBSERVATIONS"
    SPARSE_HISTORY = "SPARSE_HISTORY"


class DataQualityStatus(str, Enum):
    """Overall trustworthiness of the record behind a PatientState.

    UNTRUSTWORTHY is the state that forces risk to UNKNOWN in the trust gate.
    DEGRADED means "usable, but say so".
    """

    OK = "OK"
    DEGRADED = "DEGRADED"
    UNTRUSTWORTHY = "UNTRUSTWORTHY"


class InterventionAction(str, Enum):
    """Protocol actions. Only the deterministic protocol layer may produce these.

    The risk provider has no field capable of holding one — see
    `monitoring_result.RiskAssessment`.
    """

    ROUTINE_MONITORING = "ROUTINE_MONITORING"
    INCREASE_MONITORING = "INCREASE_MONITORING"
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    URGENT_ESCALATION = "URGENT_ESCALATION"
    REQUEST_REPEAT_OBSERVATION = "REQUEST_REPEAT_OBSERVATION"
    NOTIFY_CLINICIAN = "NOTIFY_CLINICIAN"
    NOTIFY_PATIENT = "NOTIFY_PATIENT"


class NextDoseDecision(str, Enum):
    PROCEED = "PROCEED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    HOLD = "HOLD"


class NotificationAudience(str, Enum):
    PATIENT = "PATIENT"
    CLINICIAN = "CLINICIAN"
    INVESTIGATOR = "INVESTIGATOR"


class NotificationChannel(str, Enum):
    """IN_APP is the only channel with a real provider in Phase 2.

    The others are declared so the contract is stable when real delivery
    infrastructure arrives; generating for them is not the same as sending.
    """

    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


class AdverseEventSeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class InvestigatorAction(str, Enum):
    """What a human investigator did about a monitoring cycle.

    Distinct from `InterventionAction` on purpose. An intervention is what the
    deterministic protocol *requires*; this is what a named person *decided*
    once they had read it. Keeping them in separate vocabularies is what stops
    a UI from rendering a human decision as though the protocol produced it, or
    the reverse.
    """

    ACKNOWLEDGE = "ACKNOWLEDGE"
    CONTINUE_MONITORING = "CONTINUE_MONITORING"
    HOLD_TREATMENT = "HOLD_TREATMENT"


class MonitoringEventType(str, Enum):
    """Timeline entry kinds, append-only.

    The timeline is reconstructed by ordering these, rather than by joining six
    collections by timestamp at render time.
    """

    TREATMENT_REGISTERED = "TREATMENT_REGISTERED"
    ELIGIBILITY_OVERRIDE_RECORDED = "ELIGIBILITY_OVERRIDE_RECORDED"
    DOSE_ADMINISTERED = "DOSE_ADMINISTERED"
    OBSERVATIONS_INGESTED = "OBSERVATIONS_INGESTED"
    RISK_ASSESSED = "RISK_ASSESSED"
    RISK_TRANSITION = "RISK_TRANSITION"
    DATA_QUALITY_GATE_APPLIED = "DATA_QUALITY_GATE_APPLIED"
    INTERVENTION_RAISED = "INTERVENTION_RAISED"
    NOTIFICATION_CREATED = "NOTIFICATION_CREATED"
    NEXT_DOSE_ASSESSED = "NEXT_DOSE_ASSESSED"
    ADVERSE_EVENT_RECORDED = "ADVERSE_EVENT_RECORDED"
    INVESTIGATOR_REVIEW_RECORDED = "INVESTIGATOR_REVIEW_RECORDED"
