"""Typed, individually testable read functions over `TrialReadFacade`.

`AGENT_MODE=packed` (the only mode built) calls these in a fixed order from
`evidence.py` rather than exposing them to the model as callable tools — see
`docs/FINAL_IMPLEMENTATION_PLAN.md` §12.5. They are still real functions,
not an inlined blob, so the evidence pack stays constructible and testable
without a running model.
"""

from __future__ import annotations

from .facade import TrialReadFacade
from ..schema.clinical import LabResult
from ..schema.obligations import Obligation, ObligationAction
from ..schema.result import ScreeningResult
from ..schema.trial import Criterion


def get_obligation(facade: TrialReadFacade, obligation_id: str) -> Obligation | None:
    return facade.get_obligation(obligation_id)


def get_ledger(facade: TrialReadFacade, obligation_id: str) -> list[ObligationAction]:
    return facade.get_ledger(obligation_id)


def get_screening_result(facade: TrialReadFacade, obligation: Obligation) -> ScreeningResult | None:
    """The screening that first raised this obligation — `source_ref` is a
    `ScreeningResult.result_id` for a `MISSING_LAB_EVIDENCE` obligation."""
    return facade.get_screening_result(obligation.source_ref)


def get_criterion(result: ScreeningResult | None, requirement_ref: str) -> Criterion | None:
    if result is None:
        return None
    for criterion in result.trial.criteria:
        if criterion.criterion_id == requirement_ref:
            return criterion
    return None


def get_patient_labs(result: ScreeningResult | None) -> list[LabResult]:
    if result is None:
        return []
    return list(result.patient.labs)


def get_patient_notes(result: ScreeningResult | None) -> list[str]:
    if result is None:
        return []
    return list(result.patient.notes)
