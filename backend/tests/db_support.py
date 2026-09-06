"""Shared support for the PostgreSQL-backed test files.

Not a `conftest.py` addition, deliberately — the Phase 1/2 convention
(documented in `test_monitoring_repository.py`) is that new test
infrastructure stays local rather than growing the shared fixture file. Every
test file that needs a live database imports `require_postgres()` and skips
itself when one is not reachable, so the default `pytest tests -q` run stays
network-free (docs/FINAL_IMPLEMENTATION_PLAN.md §25) while `docker compose up
-d postgres` unlocks the real thing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

TEST_DATABASE_URL = "postgresql+psycopg://trialguard:trialguard@127.0.0.1:5433/trialguard"

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def require_postgres() -> Engine:
    """An engine against the local test database, or a `pytest.skip`.

    `docker-compose.yml` at the repo root defines this exact database. Tests
    using this helper are the ones §25.4 calls database tests — real
    correctness properties that a JSON file cannot express — and they are
    allowed to need Docker precisely because they are never in the default
    import path of any other test.
    """
    from app.db.engine import build_engine

    url = os.environ.get("TEST_DATABASE_URL", TEST_DATABASE_URL)
    try:
        engine = build_engine(url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except OperationalError as exc:
        pytest.skip(f"Postgres not reachable at {url} ({exc}). Run: docker compose up -d postgres")


def real_url(engine: Engine) -> str:
    """The engine's connection URL with the password intact.

    `str(engine.url)` — an easy mistake, made once in this file already —
    renders the password as `***` for safe logging, which then fails
    authentication silently and confusingly when handed to a subprocess.
    """
    return engine.url.render_as_string(hide_password=False)


def reset_schema(engine: Engine, schema: str = "trialguard") -> None:
    """Drop and let the next migration recreate the schema — a clean slate
    for tests that need to run Alembic from scratch."""
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def alembic_upgrade_head(database_url: str) -> None:
    """Run `alembic upgrade head` as a subprocess against `database_url`.

    A subprocess, not a direct `command.upgrade()` call, so the test exercises
    exactly the command a developer or a deploy step actually runs.
    """
    env = {**os.environ, "DATABASE_URL": database_url, "MIGRATION_DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
