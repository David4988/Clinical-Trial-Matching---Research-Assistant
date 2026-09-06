"""Alembic migration correctness — docs/FINAL_IMPLEMENTATION_PLAN.md §25.4.

Skipped (not failed) when the local Postgres from `docker-compose.yml` is not
running, so the default suite stays network-free.
"""

from __future__ import annotations

import subprocess
import sys

from sqlalchemy import inspect, text

from .db_support import BACKEND_ROOT, alembic_upgrade_head, real_url, require_postgres, reset_schema


def _run_alembic(*args: str, database_url: str) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "DATABASE_URL": database_url, "MIGRATION_DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def test_upgrade_head_from_empty_succeeds():
    engine = require_postgres()
    reset_schema(engine)
    alembic_upgrade_head(real_url(engine))

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names(schema="trialguard"))
    expected = {
        "patients",
        "trials",
        "screening_results",
        "treatments",
        "monitoring_cycles",
        "observations",
        "adverse_events",
        "monitoring_events",
        "notifications",
        "alembic_version",
    }
    assert expected <= tables


def test_downgrade_base_succeeds():
    engine = require_postgres()
    reset_schema(engine)
    alembic_upgrade_head(real_url(engine))

    result = _run_alembic("downgrade", "base", database_url=real_url(engine))
    assert result.returncode == 0, result.stderr

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names(schema="trialguard"))
    # Alembic's own bookkeeping table is the only thing left behind.
    assert tables <= {"alembic_version"}

    # Leave the schema in a usable state for any test that runs after this one.
    alembic_upgrade_head(real_url(engine))


def test_autogenerate_produces_no_diff():
    """The single most important migration test: `db/tables.py` and the
    applied revisions must describe exactly the same schema, or the two have
    drifted and a future `alembic revision --autogenerate` would silently
    encode someone's forgotten manual change."""
    engine = require_postgres()
    reset_schema(engine)
    alembic_upgrade_head(real_url(engine))

    result = _run_alembic("check", database_url=real_url(engine))
    assert result.returncode == 0, (
        f"alembic check detected drift between db/tables.py and the applied "
        f"migrations:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
