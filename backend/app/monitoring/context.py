"""Wiring for the Phase 2 services.

Bundles the three monitoring services so `main.py` gains one attribute rather
than four, and so tests can build the whole stack over temp stores in one call.

The screening repository is *passed in* rather than constructed here: Phase 2
reads Phase 1's results through the existing `Repository` interface, and there
must only ever be one screening store in play.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ingestion import ObservationIngestionService
from .notifications import NotificationDeliveryProvider
from .service import MonitoringService
from .treatment import TreatmentService
from ..repository.base import Repository
from ..repository.json_monitoring import JsonMonitoringRepository
from ..repository.monitoring_base import MonitoringRepository
from ..risk.provider import RiskProvider


@dataclass
class MonitoringContext:
    repository: MonitoringRepository
    treatment: TreatmentService
    ingestion: ObservationIngestionService
    monitoring: MonitoringService

    @classmethod
    def build(
        cls,
        screening_repository: Repository,
        monitoring_repository: MonitoringRepository | None = None,
        risk_provider: RiskProvider | None = None,
        notification_provider: NotificationDeliveryProvider | None = None,
    ) -> MonitoringContext:
        repository = monitoring_repository or JsonMonitoringRepository()
        return cls(
            repository=repository,
            treatment=TreatmentService(screening_repository, repository),
            ingestion=ObservationIngestionService(repository),
            monitoring=MonitoringService(
                repository,
                risk_provider=risk_provider,
                notification_provider=notification_provider,
            ),
        )
