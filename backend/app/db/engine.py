"""Engine construction and connection configuration.

Follows the existing convention exactly: bare `os.environ.get()`, read once,
module-level `ENV_VAR` constants, and a default that lets local development
proceed with the least ceremony. See `repository/paths.py` and
`risk/factory.py` for the precedent this copies.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

DATABASE_URL_ENV = "DATABASE_URL"
DB_SCHEMA_ENV = "DB_SCHEMA"
DB_POOL_SIZE_ENV = "DB_POOL_SIZE"
DB_STATEMENT_TIMEOUT_MS_ENV = "DB_STATEMENT_TIMEOUT_MS"
SQL_ECHO_ENV = "SQL_ECHO"

DEFAULT_SCHEMA = "trialguard"
DEFAULT_POOL_SIZE = 5
DEFAULT_STATEMENT_TIMEOUT_MS = 15_000
DEFAULT_CONNECT_TIMEOUT_S = 10


def schema_name() -> str:
    """The Postgres schema every table lives in. Never `public` — see
    `docs/FINAL_IMPLEMENTATION_PLAN.md` §10.3."""
    configured = os.environ.get(DB_SCHEMA_ENV, "").strip()
    return configured or DEFAULT_SCHEMA


def database_url() -> str | None:
    """`None` when unset — the caller decides what that means (§11.5: the
    JSON rollback path)."""
    configured = os.environ.get(DATABASE_URL_ENV, "").strip()
    return configured or None


def build_engine(url: str | None = None) -> Engine:
    """Construct (but do not connect) an Engine for `url` or `DATABASE_URL`.

    Raises `RuntimeError` if no URL is available — the caller
    (`repository/factory.py`) is the one place that decides a missing or
    unreachable database means falling back to JSON, never this module.
    """
    resolved_url = url or database_url()
    if not resolved_url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is not set; cannot build a database engine."
        )

    pool_size = int(os.environ.get(DB_POOL_SIZE_ENV, str(DEFAULT_POOL_SIZE)))
    statement_timeout_ms = int(
        os.environ.get(DB_STATEMENT_TIMEOUT_MS_ENV, str(DEFAULT_STATEMENT_TIMEOUT_MS))
    )
    echo = os.environ.get(SQL_ECHO_ENV, "false").strip().lower() == "true"
    schema = schema_name()

    return create_engine(
        resolved_url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=True,
        future=True,
        connect_args={
            "connect_timeout": DEFAULT_CONNECT_TIMEOUT_S,
            "options": f"-c search_path={schema} -c statement_timeout={statement_timeout_ms}",
        },
    )
