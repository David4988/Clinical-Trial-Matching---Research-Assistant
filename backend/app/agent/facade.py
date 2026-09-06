"""`TrialReadFacade` — the only thing `agent/` imports from the rest of the
application, and the enforced boundary: read methods only, no write method
exists at all. `docs/FINAL_IMPLEMENTATION_PLAN.md` §12.2.
"""

from __future__ import annotations

from ..repository.base import Repository
from ..repository.obligation_base import ObligationRepository
from ..schema.obligations import Obligation, ObligationAction, ResponsibleParty
from ..schema.result import ScreeningResult


class TrialReadFacade:
    def __init__(self, obligation_repository: ObligationRepository, screening_repository: Repository) -> None:
        self._obligations = obligation_repository
        self._screening = screening_repository

    def get_obligation(self, obligation_id: str) -> Obligation | None:
        return self._obligations.get_obligation(obligation_id)

    def get_ledger(self, obligation_id: str) -> list[ObligationAction]:
        return self._obligations.list_actions(obligation_id)

    def get_screening_result(self, result_id: str) -> ScreeningResult | None:
        return self._screening.get_screening_result(result_id)

    def get_party(self, party_id: str | None) -> ResponsibleParty | None:
        if party_id is None:
            return None
        return self._obligations.get_party(party_id)
