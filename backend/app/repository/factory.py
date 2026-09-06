"""Choosing which persistence backend the application runs against.

Mirrors `risk/factory.py` deliberately: a deployment decision made once at
startup, read from one environment variable, with a probe that proves the
chosen backend actually works before the application commits to it, and a
**never-raise** contract — a TrialGuard that boots on the JSON fallback is
strictly better than one that refuses to start. See
`docs/FINAL_IMPLEMENTATION_PLAN.md` §11.5.

    postgres   SqlRepository + SqlMonitoringRepository   PostgreSQL / Supabase
    json       JsonRepository + JsonMonitoringRepository the rollback path

`PERSISTENCE` selects explicitly. Left unset, the presence of `DATABASE_URL`
decides: set it and you get Postgres; leave it unset and the app boots on
JSON with zero configuration, which is what keeps the default test suite and
a from-scratch developer checkout network-free.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .base import Repository
from .json_repo import JsonRepository
from .json_monitoring import JsonMonitoringRepository
from .monitoring_base import MonitoringRepository

logger = logging.getLogger("app.repository.factory")

POSTGRES = "postgres"
JSON = "json"

BACKEND_NAMES = (POSTGRES, JSON)

ENV_VAR = "PERSISTENCE"


@dataclass(frozen=True)
class RepositoryBundle:
    repository: Repository
    monitoring_repository: MonitoringRepository
    backend: str
    #: True when the caller asked for `postgres` but the app is actually
    #: running on the JSON fallback — the fact `/health` surfaces (§23.10).
    degraded: bool = False


def build_repositories(name: str | None = None) -> RepositoryBundle:
    """Construct the repository pair for the chosen backend.

    Never raises. `postgres` is attempted only if a `DATABASE_URL` is
    actually configured; any failure to build or reach it falls back to
    `json`, logged once, with `degraded=True` on the returned bundle.
    """
    configured = os.environ.get(ENV_VAR, "").strip().lower()
    if configured and configured not in BACKEND_NAMES:
        logger.warning(
            "Unknown %s=%r; expected one of %s. Falling back to json.",
            ENV_VAR,
            configured,
            ", ".join(BACKEND_NAMES),
        )
        configured = ""

    if not configured:
        from ..db.engine import database_url

        configured = POSTGRES if database_url() else JSON

    chosen = name or configured

    if chosen == JSON:
        return RepositoryBundle(
            repository=JsonRepository(),
            monitoring_repository=JsonMonitoringRepository(),
            backend=JSON,
        )

    # chosen == POSTGRES
    try:
        from ..db.engine import build_engine
        from .sql_repo import SqlRepository
        from .sql_monitoring import SqlMonitoringRepository

        engine = build_engine()
        _probe(engine)
        return RepositoryBundle(
            repository=SqlRepository(engine),
            monitoring_repository=SqlMonitoringRepository(engine),
            backend=POSTGRES,
        )
    except Exception as exc:  # noqa: BLE001 - startup must not fail here
        logger.error(
            "Could not start the PostgreSQL persistence backend (%s); "
            "falling back to the JSON store. The application will run "
            "degraded until DATABASE_URL is reachable.",
            exc,
        )
        return RepositoryBundle(
            repository=JsonRepository(),
            monitoring_repository=JsonMonitoringRepository(),
            backend=JSON,
            degraded=True,
        )


def _probe(engine) -> None:
    """Prove the database actually answers before committing to it — the
    same instinct as `risk/factory.py`'s `provider._engine.metadata` touch."""
    from sqlalchemy import text

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
