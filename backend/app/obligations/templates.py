"""Deterministic draft generation — the floor every provider degrades to.

`docs/FINAL_IMPLEMENTATION_PLAN.md` §12.4: the template provider is a normal
provider implementation, not an exception-only fallback branch. It is also
what backs WhatsApp's approved-template constraint (§18.2): `template_name`
and `template_params` are ALWAYS produced here, never by a model, regardless
of which provider wrote `subject`/`body`.
"""

from __future__ import annotations

from ..schema.obligation_enums import ObligationType, ProposedActionType
from ..schema.obligations import Obligation

TEMPLATE_NAME = "trialguard_evidence_request"


def action_type_for(obligation: Obligation) -> ProposedActionType:
    if obligation.type is ObligationType.MISSING_LAB_EVIDENCE:
        return ProposedActionType.REQUEST_LAB_EVIDENCE
    return ProposedActionType.REQUEST_REPEAT_OBSERVATION


def template_params_for(obligation: Obligation) -> list[str]:
    """Facts, not prose — the model never invents these."""
    return [obligation.patient_id, obligation.requirement_ref, obligation.trial_id]


def draft_subject(obligation: Obligation) -> str:
    return f"{obligation.trial_id} / {obligation.patient_id} — {obligation.title}"


def draft_body(obligation: Obligation) -> str:
    lines = [
        f"Screening for {obligation.patient_id} against {obligation.trial_id} "
        f"cannot complete because requirement {obligation.requirement_ref} "
        f"({obligation.requirement_text}) has no result on file.",
    ]
    notes = [e.snippet for e in obligation.evidence if e.snippet]
    if notes:
        lines.append("Relevant record note: " + "; ".join(notes))
    lines.append(
        "Could you confirm whether the result is available and provide it?"
    )
    return "\n\n".join(lines)


def draft_reason(obligation: Obligation) -> str:
    return (
        f"{obligation.requirement_ref} is unresolved because no evidence "
        f"exists for '{obligation.requirement_text}'."
    )
