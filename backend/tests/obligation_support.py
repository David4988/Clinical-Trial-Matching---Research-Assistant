"""Shared helpers for obligation-layer tests. Not a conftest.py addition,
matching the repository's convention of keeping new test infra local
(`tests/db_support.py` does the same)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.monitoring.context import MonitoringContext
from app.obligations.context import ObligationContext
from app.repository.json_obligations import JsonObligationRepository
from app.repository.json_repo import JsonRepository
from app.repository.json_monitoring import JsonMonitoringRepository
from app.service import ScreeningService


def build_client(tmp_path) -> TestClient:
    """A fully wired app — screening + monitoring + obligations — all over
    isolated JSON stores under `tmp_path`, so tests never touch
    `backend/data/` or each other."""
    service = ScreeningService(repository=JsonRepository(tmp_path / "store.json"))
    monitoring = MonitoringContext.build(
        service.repository,
        monitoring_repository=JsonMonitoringRepository(tmp_path / "monitoring.json"),
    )
    obligations = ObligationContext.build(
        monitoring.repository,
        obligation_repository=JsonObligationRepository(tmp_path / "obligations.json"),
        screening_repository=service.repository,
    )
    return TestClient(create_app(service=service, monitoring=monitoring, obligations=obligations))
