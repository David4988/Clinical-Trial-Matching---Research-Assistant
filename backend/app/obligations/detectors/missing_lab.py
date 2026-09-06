"""Missing-lab-evidence detector.

Runs the real vertical slice: CT-001 / P-3311 / INC-04 / lab:eGFR / UNKNOWN.
A criterion evaluates to `UNKNOWN` for many reasons (unit mismatch, an
unsupported rule, a genuinely absent lab); this detector only fires for the
specific, actionable case — a *numeric lab rule* whose result is `UNKNOWN`
because the referenced lab is simply not on file. That is the honest,
narrow scope: it does not invent a requirement the screening engine did not
already surface.
"""

from __future__ import annotations

from ...schema.enums import CriterionStatus
from ...schema.obligation_enums import DetectorSource, ObligationType
from ...schema.obligations import DetectedRequirement
from ...schema.result import ScreeningResult
from ...schema.trial import LAB_PREFIX


def detect(result: ScreeningResult) -> list[DetectedRequirement]:
    """Pure. Reads only the snapshot embedded in `result` — never today's
    patient/trial record, so a re-screen with fresh evidence is what changes
    the answer, not a mutation to something already screened."""

    criteria_by_id = {c.criterion_id: c for c in result.trial.criteria}
    detected: list[DetectedRequirement] = []

    for criterion_result in result.criteria_results:
        if criterion_result.status is not CriterionStatus.UNKNOWN:
            continue
        criterion = criteria_by_id.get(criterion_result.criterion_id)
        if criterion is None or criterion.rule is None:
            continue
        if criterion.rule.type != "numeric":
            continue
        if not criterion.rule.field.startswith(LAB_PREFIX):
            continue

        detected.append(
            DetectedRequirement(
                type=ObligationType.MISSING_LAB_EVIDENCE,
                trial_id=result.trial.trial_id,
                patient_id=result.patient.patient_id,
                requirement_ref=criterion.criterion_id,
                requirement_text=criterion.text,
                protocol_id=result.trial.trial_id,
                source_ref=result.result_id,
                evidence=list(criterion_result.evidence),
            )
        )

    return detected


SOURCE = DetectorSource.SCREENING
