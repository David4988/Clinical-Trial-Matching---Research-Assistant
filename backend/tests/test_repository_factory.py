"""`repository/factory.py` — mirrors `test_risk_provider.py`'s coverage of
`risk/factory.py`: the factory must never raise, must degrade to the JSON
store on any failure, and must choose the backend the environment asks for.
"""

from __future__ import annotations

import pytest

from app.repository.factory import JSON, POSTGRES, build_repositories
from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.json_repo import JsonRepository


def test_defaults_to_json_with_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PERSISTENCE", raising=False)

    bundle = build_repositories()

    assert bundle.backend == JSON
    assert bundle.degraded is False
    assert isinstance(bundle.repository, JsonRepository)
    assert isinstance(bundle.monitoring_repository, JsonMonitoringRepository)


def test_explicit_json_wins_even_with_database_url_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/does-not-matter")
    monkeypatch.setenv("PERSISTENCE", "json")

    bundle = build_repositories()

    assert bundle.backend == JSON
    assert bundle.degraded is False


def test_unreachable_postgres_degrades_to_json_and_never_raises(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/unreachable"
    )
    monkeypatch.delenv("PERSISTENCE", raising=False)

    bundle = build_repositories()  # must not raise

    assert bundle.backend == JSON
    assert bundle.degraded is True
    assert isinstance(bundle.repository, JsonRepository)


def test_unknown_persistence_value_falls_back_to_json(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PERSISTENCE", "sqlite-please")

    bundle = build_repositories()

    assert bundle.backend == JSON
    assert bundle.degraded is False


def test_explicit_name_argument_overrides_environment(monkeypatch):
    monkeypatch.setenv("PERSISTENCE", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    bundle = build_repositories(name="json")

    assert bundle.backend == JSON


def test_postgres_chosen_when_reachable():
    from .db_support import real_url, require_postgres

    engine = require_postgres()  # skips this test if Postgres is not running

    import os

    from app.repository.sql_monitoring import SqlMonitoringRepository
    from app.repository.sql_repo import SqlRepository

    os.environ["DATABASE_URL"] = real_url(engine)
    try:
        bundle = build_repositories()
        assert bundle.backend == POSTGRES
        assert bundle.degraded is False
        assert isinstance(bundle.repository, SqlRepository)
        assert isinstance(bundle.monitoring_repository, SqlMonitoringRepository)
    finally:
        del os.environ["DATABASE_URL"]
