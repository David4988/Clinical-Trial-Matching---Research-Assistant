"""Deterministic rules: identity, priority, and the title/detail templates.

Nothing here is the LLM's job. `docs/FINAL_IMPLEMENTATION_PLAN.md` §6.1, §20.1.
"""

from __future__ import annotations

from ..schema.enums import CriterionKind
from ..schema.obligation_enums import ObligationPriority, ObligationType


def obligation_key(
    trial_id: str,
    patient_id: str,
    type: ObligationType,
    requirement_ref: str,
    occurrence: str = "",
) -> str:
    """The deterministic natural key — the entire deduplication mechanism.
    No clock, no counter, no random id participates."""
    return "|".join([trial_id, patient_id, type.value, requirement_ref, occurrence])


_RECONFIRM_LEDGER_INTERVAL_HOURS = 6


def reconfirm_interval_hours() -> int:
    return _RECONFIRM_LEDGER_INTERVAL_HOURS


def priority_for(
    *,
    criterion_kind: CriterionKind | None,
    has_active_treatment: bool,
    age_days: int,
    escalation_count: int,
) -> ObligationPriority:
    """All inputs deterministic: criterion kind (EXCLUSION outranks
    INCLUSION), whether the patient has an active treatment, age since
    first detection, and prior escalations. Never the model."""
    score = 0
    if criterion_kind is CriterionKind.EXCLUSION:
        score += 2
    else:
        score += 1
    if has_active_treatment:
        score += 1
    if age_days >= 7:
        score += 1
    if age_days >= 14:
        score += 1
    score += min(escalation_count, 2)

    if score >= 5:
        return ObligationPriority.URGENT
    if score >= 3:
        return ObligationPriority.HIGH
    if score >= 2:
        return ObligationPriority.MEDIUM
    return ObligationPriority.LOW


def title_for(type: ObligationType, requirement_ref: str, requirement_text: str) -> str:
    if type is ObligationType.MISSING_LAB_EVIDENCE:
        lab = requirement_text
        return f"Evidence required by {requirement_ref} is not on file"
    return f"Required observation for {requirement_ref} is missing"


def detail_for(
    type: ObligationType,
    requirement_ref: str,
    requirement_text: str,
    patient_id: str,
) -> str:
    if type is ObligationType.MISSING_LAB_EVIDENCE:
        return (
            f"Screening criterion {requirement_ref} could not be evaluated for "
            f"{patient_id}: the record has no result for the required "
            f"measurement ({requirement_text})."
        )
    return (
        f"Monitoring requires an observation for {requirement_ref} "
        f"({requirement_text}) that has not been recorded for {patient_id}."
    )
