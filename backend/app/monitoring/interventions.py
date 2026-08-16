"""The intervention engine — deterministic protocol response.

This is where Phase 2 decides what happens, and it is deliberately dull: a
lookup in `protocol.ACTIONS_BY_LEVEL` keyed by the *effective* risk level, plus
the evidence explaining why. There is no model here, no scoring, and no
judgement of its own.

The separation matters. A risk provider says "this looks like RED". This module
says "the protocol requires urgent escalation at RED". Swapping the provider for
a trained model changes the first sentence and leaves the second untouched — and
a provider can never reach into this table.

The UNKNOWN branch is the one to read carefully: it does not fall back to
routine monitoring. Untrustworthy data produces *more* attention, not less.
"""

from __future__ import annotations

from datetime import datetime

from . import ids, protocol
from ..schema.clinical import Evidence
from ..schema.enums import EvidenceSource, Severity
from ..schema.monitoring_enums import InterventionAction, RiskLevel
from ..schema.monitoring_result import (
    EffectiveRisk,
    Intervention,
    PatientState,
    RiskAssessment,
)

#: Actions that raise the alarm rather than merely adjust cadence.
_ESCALATING = {
    InterventionAction.CLINICAL_REVIEW,
    InterventionAction.URGENT_ESCALATION,
    InterventionAction.NOTIFY_CLINICIAN,
    InterventionAction.NOTIFY_PATIENT,
    InterventionAction.REQUEST_REPEAT_OBSERVATION,
}

#: Actions that change how often the patient is measured.
_CADENCE = {
    InterventionAction.ROUTINE_MONITORING,
    InterventionAction.INCREASE_MONITORING,
}

_ACTION_RATIONALE: dict[InterventionAction, str] = {
    InterventionAction.ROUTINE_MONITORING: (
        "Continue the protocol's routine observation schedule."
    ),
    InterventionAction.INCREASE_MONITORING: (
        "Increase observation frequency so any further movement is caught early."
    ),
    InterventionAction.CLINICAL_REVIEW: (
        "A clinician must review this patient before the next scheduled dose."
    ),
    InterventionAction.URGENT_ESCALATION: (
        "Escalate now. The protocol treats this as requiring immediate attention."
    ),
    InterventionAction.REQUEST_REPEAT_OBSERVATION: (
        "Repeat the missing or stale observations. Risk cannot be assessed "
        "until trustworthy readings are available, and the absence of data is "
        "not treated as reassurance."
    ),
    InterventionAction.NOTIFY_CLINICIAN: (
        "Notify the responsible clinician or investigator."
    ),
    InterventionAction.NOTIFY_PATIENT: (
        "Notify the patient, subject to investigator approval."
    ),
}


def build_interventions(
    state: PatientState,
    effective_risk: EffectiveRisk,
    risk: RiskAssessment,
    now: datetime,
) -> list[Intervention]:
    """Apply the protocol response table to the effective risk level."""
    level = effective_risk.level
    rule_id = protocol.RULE_IDS[level]
    interval = protocol.MONITORING_INTERVAL_MINUTES[level]
    evidence = _evidence(state, effective_risk, risk, rule_id)

    return [
        Intervention(
            intervention_id=ids.new_id(ids.INTERVENTION),
            patient_id=state.patient_id,
            trial_id=state.trial_id,
            raised_at=now,
            action=action,
            severity=_severity(level, action),
            rationale=_ACTION_RATIONALE[action],
            protocol_rule_id=rule_id,
            risk_level=level,
            monitoring_interval_minutes=interval if action in _CADENCE else None,
            evidence=evidence,
        )
        for action in protocol.ACTIONS_BY_LEVEL[level]
    ]


def monitoring_interval_for(level: RiskLevel) -> int:
    """The cadence the protocol mandates at this level, in minutes."""
    return protocol.MONITORING_INTERVAL_MINUTES[level]


def _severity(level: RiskLevel, action: InterventionAction) -> Severity:
    """Reuses the Phase 1 INFO/WARN scale rather than inventing a third."""
    if level is RiskLevel.GREEN:
        return Severity.INFO
    return Severity.WARN if action in _ESCALATING or level is RiskLevel.RED else Severity.INFO


def _evidence(
    state: PatientState,
    effective_risk: EffectiveRisk,
    risk: RiskAssessment,
    rule_id: str,
) -> list[Evidence]:
    """Why this action was taken, in the order a reviewer would want it.

    Protocol rule first (the authority), then the model's reading, then the
    measurements themselves. Reuses the Phase 1 `Evidence` primitive so the
    frontend renders it with the same component as a screening verdict.
    """
    evidence = [
        Evidence(
            source_type=EvidenceSource.RULE,
            locator=rule_id,
            snippet=f"{protocol.PROTOCOL_ID}: {effective_risk.level.value}",
            note=protocol.LEVEL_RATIONALE[effective_risk.level],
        )
    ]

    if effective_risk.gated:
        # The gate overrode the model. Say so, and say what it overrode.
        evidence.append(
            Evidence(
                source_type=EvidenceSource.RULE,
                locator="DATA-QUALITY-GATE",
                snippet=(
                    f"Provider reported {effective_risk.provider_level.value}; "
                    f"applied level is {effective_risk.level.value}."
                ),
                note=effective_risk.reason,
            )
        )
    else:
        evidence.append(
            Evidence(
                source_type=EvidenceSource.RISK_MODEL,
                locator=f"{risk.provider}@{risk.model_version}",
                snippet=(
                    f"level {risk.level.value}, score {risk.score:.2f}, "
                    f"confidence {risk.confidence:.2f}"
                ),
                note="Advisory only. The protocol table above decided the action.",
            )
        )

    for factor in risk.contributing_factors[:4]:
        evidence.append(
            Evidence(
                source_type=EvidenceSource.OBSERVATION,
                locator=factor.factor,
                snippet=factor.detail,
                note=f"Contribution weight {factor.weight:.2f}.",
            )
        )

    for flag in state.data_quality.flags:
        evidence.append(
            Evidence(
                source_type=EvidenceSource.OBSERVATION,
                locator=flag.code.value,
                snippet=flag.message,
                note=f"Data quality: {state.data_quality.status.value}.",
            )
        )

    return evidence
