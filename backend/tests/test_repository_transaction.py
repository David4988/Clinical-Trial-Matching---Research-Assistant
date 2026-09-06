"""`Repository.transaction()` / `MonitoringRepository.transaction()`.

The JSON side offers no atomicity, explicitly (`docs/FINAL_IMPLEMENTATION_PLAN.md`
§9.6, §11.4) — `transaction()` is a `nullcontext`, so a failure partway
through a block leaves whatever was already written, written. The SQL side
does the opposite: nothing commits until the block exits cleanly. Both
behaviours are contracts, not accidents, and this file is what keeps them
honest.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.json_repo import JsonRepository
from app.repository.session_stub import json_transaction


def test_json_repository_transaction_is_a_nullcontext(tmp_path):
    repo = JsonRepository(tmp_path / "store.json")
    with repo.transaction() as value:
        assert value is None  # nullcontext yields None


def test_json_monitoring_repository_transaction_is_a_nullcontext(tmp_path):
    repo = JsonMonitoringRepository(tmp_path / "monitoring.json")
    with repo.transaction() as value:
        assert value is None


def test_json_transaction_helper_returns_a_context_manager():
    ctx = json_transaction()
    assert isinstance(ctx, AbstractContextManager)
    with ctx:
        pass  # must not raise


def test_json_repository_offers_no_atomicity_by_design(tmp_path):
    """A failure inside the block does not undo the write that already
    happened — this IS the JSON store's documented limitation, asserted so a
    future change cannot silently claim atomicity it does not provide."""
    from app.fixtures_loader import load_patient

    repo = JsonRepository(tmp_path / "store.json")
    patient = load_patient("patient_incomplete")

    try:
        with repo.transaction():
            repo.save_patient(patient)
            raise RuntimeError("simulated failure mid-block")
    except RuntimeError:
        pass

    data = repo._load()  # noqa: SLF001 - test-only introspection
    assert patient.patient_id in data["patients"]
