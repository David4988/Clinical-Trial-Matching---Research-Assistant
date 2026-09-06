"""Alembic environment.

Reads the connection URL from the environment, never from `alembic.ini` —
`MIGRATION_DATABASE_URL` if set, else `DATABASE_URL`, matching
`docs/FINAL_IMPLEMENTATION_PLAN.md` §10.5 and §29: Alembic uses a direct
connection, never the transaction-mode pooler, because DDL and advisory locks
do not survive it.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.tables import metadata  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _include_object(object, name, type_, reflected, compare_to):
    """Exclude Alembic's own version table from the autogenerate diff.

    A known quirk: with `include_schemas=True` and a non-`public`
    `version_table_schema`, the reflected version table can come back with
    `schema=None` even though it physically lives in `target_metadata.schema`,
    which makes autogenerate propose dropping and recreating it. It is our
    own bookkeeping table, never part of the domain schema, so it is excluded
    outright rather than worked around per-revision.
    """
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def _migration_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL", "").strip()
    if url:
        return url
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    raise RuntimeError(
        "Set MIGRATION_DATABASE_URL or DATABASE_URL before running Alembic."
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=_include_object,
        version_table_schema=target_metadata.schema,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _migration_url()
    # Force `search_path=public` on this connection, explicitly overriding
    # Postgres's own default (`"$user", public`). Because the database role
    # used in development is named the same as the schema (`trialguard`),
    # Postgres's `"$user"` resolution silently makes `trialguard` the
    # connection's default schema unless told otherwise. SQLAlchemy's
    # Postgres dialect computes `default_schema_name` from that default; if
    # it is `trialguard`, every reflected foreign key into `trialguard.*`
    # comes back with `referred_schema=None` ("the default schema"), which
    # does not equal our metadata's explicit `schema="trialguard"` and
    # produces a permanent false autogenerate diff. Pinning the default to
    # `public` keeps every reflected reference to `trialguard.*` explicit,
    # matching the metadata exactly, regardless of what role runs the
    # migration.
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"options": "-c search_path=public"},
    )

    with connectable.connect() as connection:
        # Alembic's own version table lives in the target schema, which the
        # first revision is what creates — so it must exist before Alembic
        # tries to write to it. `IF NOT EXISTS` makes this idempotent on
        # every later run.
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{target_metadata.schema}"'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=_include_object,
            version_table_schema=target_metadata.schema,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
