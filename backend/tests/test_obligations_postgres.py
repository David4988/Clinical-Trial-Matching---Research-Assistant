"""The same acceptance loop as `test_obligations_e2e.py`, over
`SqlObligationRepository` — proving the real `obligations_active_key` partial
unique index is what backs deduplication, not just application logic.
Skips (never fails) when Postgres is unreachable, exactly like
`test_migrations.py` / `test_repository_parity.py`."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.monitoring.context import MonitoringContext
from app.obligations.context import ObligationContext
from app.repository.sql_monitoring import SqlMonitoringRepository
from app.repository.sql_obligations import SqlObligationRepository
from app.repository.sql_repo import SqlRepository
from app.service import ScreeningService

from .db_support import require_postgres, reset_schema

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _build_client(engine):
    service = ScreeningService(repository=SqlRepository(engine))
    monitoring = MonitoringContext.build(service.repository, monitoring_repository=SqlMonitoringRepository(engine))
    obligations = ObligationContext.build(
        monitoring.repository,
        obligation_repository=SqlObligationRepository(engine),
        screening_repository=service.repository,
    )
    return TestClient(create_app(service=service, monitoring=monitoring, obligations=obligations))


def test_postgres_backed_dedup_and_full_loop():
    engine = require_postgres()
    reset_schema(engine)
    from tests.db_support import alembic_upgrade_head, real_url

    alembic_upgrade_head(real_url(engine))

    client = _build_client(engine)
    patient = json.loads((FIXTURES / "patient_incomplete.json").read_text())
    trial = json.loads((FIXTURES / "trial_demo.json").read_text())

    for _ in range(3):
        client.post("/screen", json={"patient": patient, "trial": trial})

    obligations = client.get("/obligations", params={"trial_id": "CT-001"}).json()
    assert obligations["count"] == 1  # the real partial unique index, not just app logic
    obligation_id = obligations["obligations"][0]["obligation_id"]

    proposal = client.post(f"/obligations/{obligation_id}/investigate").json()
    approved = client.post(
        f"/obligations/proposals/{proposal['proposal_id']}/approve",
        json={"reviewer": "Dr. Rao", "note": "Reviewed."},
    ).json()
    assert approved["status"] == "EXECUTED"

    patient_with_egfr = copy.deepcopy(patient)
    patient_with_egfr["labs"].append({"name": "eGFR", "value": 60, "unit": "mL/min", "observed_at": "2026-02-01"})
    client.post("/screen", json={"patient": patient_with_egfr, "trial": trial})

    resolved = client.get(f"/obligations/{obligation_id}").json()
    assert resolved["status"] == "RESOLVED"
