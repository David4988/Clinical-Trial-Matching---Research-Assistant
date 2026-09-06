"""Evidence assembly: calls `tools.py` in a fixed order and assembles one
evidence pack. `AGENT_MODE=packed` — one fixed pipeline, not a tool-calling
loop. `docs/FINAL_IMPLEMENTATION_PLAN.md` §12.5.

Evidence gaps are never auto-resolved: a gap is recorded in the pack and
investigation proceeds with what it has.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import tools
from .facade import TrialReadFacade
from ..schema.obligations import Obligation, ObligationAction

#: The fixed order every investigation calls tools in — recorded verbatim
#: into `ProposalProvenance.tools_called` so a reviewer can see exactly what
#: the agent read, not just what it wrote.
TOOL_ORDER = (
    "get_obligation",
    "get_ledger",
    "get_screening_result",
    "get_criterion",
    "get_patient_labs",
    "get_patient_notes",
)


@dataclass
class EvidencePack:
    obligation: Obligation
    ledger: list[ObligationAction] = field(default_factory=list)
    requirement_text: str = ""
    lab_names_on_file: list[str] = field(default_factory=list)
    patient_notes: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)


def assemble_evidence_pack(obligation: Obligation, facade: TrialReadFacade) -> EvidencePack:
    pack = EvidencePack(obligation=obligation)

    pack.tools_called.append("get_obligation")  # already resolved by the caller; recorded for provenance parity

    ledger = tools.get_ledger(facade, obligation.obligation_id)
    pack.tools_called.append("get_ledger")
    pack.ledger = ledger

    result = tools.get_screening_result(facade, obligation)
    pack.tools_called.append("get_screening_result")
    if result is None:
        pack.gaps.append(f"Source screening result '{obligation.source_ref}' could not be read.")

    criterion = tools.get_criterion(result, obligation.requirement_ref)
    pack.tools_called.append("get_criterion")
    pack.requirement_text = criterion.text if criterion else obligation.requirement_text

    labs = tools.get_patient_labs(result)
    pack.tools_called.append("get_patient_labs")
    pack.lab_names_on_file = [lab.name for lab in labs]

    notes = tools.get_patient_notes(result)
    pack.tools_called.append("get_patient_notes")
    pack.patient_notes = notes

    return pack


def render_user_content(pack: EvidencePack) -> str:
    """Deterministic prose rendering of the evidence pack — the only thing
    the model actually reads."""
    obligation = pack.obligation
    lines = [
        f"Trial: {obligation.trial_id}",
        f"Patient: {obligation.patient_id}",
        f"Requirement: {obligation.requirement_ref} — {pack.requirement_text}",
        f"Obligation type: {obligation.type.value}",
        f"Detected: {obligation.first_detected_at.isoformat()}",
        f"Escalations so far: {obligation.escalation_count}",
    ]
    if pack.lab_names_on_file:
        lines.append(f"Labs currently on file for this patient: {', '.join(pack.lab_names_on_file)}")
    else:
        lines.append("Labs currently on file for this patient: none")
    if pack.patient_notes:
        lines.append("Record notes: " + "; ".join(pack.patient_notes))
    if pack.ledger:
        lines.append("Follow-up history:")
        for action in pack.ledger:
            lines.append(f"  - #{action.seq} {action.kind.value} at {action.occurred_at.isoformat()}")
    if pack.gaps:
        lines.append("Known gaps in this evidence pack: " + "; ".join(pack.gaps))
    lines.append(
        "Draft a short message requesting the missing evidence. Base every "
        "factual claim only on what is stated above."
    )
    return "\n".join(lines)
