"""Wiring for the obligation layer services — the same pattern as
`monitoring/context.py`: bundle related services so `main.py` gains one
attribute, and tests can build the whole stack over temp stores in one call.
"""

from __future__ import annotations

from dataclasses import dataclass

from .execution import ExecutionService
from .proposals import ObligationProposalService
from .service import ObligationService
from ..agent.facade import TrialReadFacade
from ..agent.model.factory import build_model_provider
from ..fixtures_loader import load_parties
from ..repository.base import Repository
from ..repository.json_obligations import JsonObligationRepository
from ..repository.json_repo import JsonRepository
from ..repository.monitoring_base import MonitoringRepository
from ..repository.obligation_base import ObligationRepository


@dataclass
class ObligationContext:
    repository: ObligationRepository
    service: ObligationService
    proposals: ObligationProposalService

    @classmethod
    def build(
        cls,
        monitoring_repository: MonitoringRepository,
        obligation_repository: ObligationRepository | None = None,
        screening_repository: Repository | None = None,
        seed_parties: bool = True,
    ) -> ObligationContext:
        repository = obligation_repository or JsonObligationRepository()
        service = ObligationService(repository)
        execution = ExecutionService(monitoring_repository)

        # `MODEL_PROVIDER` read once at startup here, mirroring
        # `risk/factory.py` / `repository/factory.py` — never raises, falls
        # back to `TemplateProvider` on any startup probe failure.
        model_provider = build_model_provider()
        facade = TrialReadFacade(repository, screening_repository or JsonRepository())
        proposals = ObligationProposalService(
            repository, service, execution, facade=facade, model_provider=model_provider
        )

        if seed_parties:
            for party in load_parties():
                repository.save_party(party)

        return cls(repository=repository, service=service, proposals=proposals)
