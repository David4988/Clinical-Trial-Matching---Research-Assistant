"""Session lifecycle and the transaction unit-of-work.

`SessionScopedRepository` is the base both `SqlRepository` and
`SqlMonitoringRepository` inherit. It gives every method a session without
making the service layer aware sessions exist:

- Outside a `transaction()` block, each repository method opens its own
  session, commits, and closes it — the same one-call-one-write shape the
  JSON repositories already have.
- Inside a `transaction()` block, every repository call sharing this instance
  (or another repository sharing the same engine and joining the same
  transaction — see `transaction()`'s docstring) uses the one open session,
  and commits or rolls back together. This is what makes
  `docs/FINAL_IMPLEMENTATION_PLAN.md` §9.6's "all writes commit together or
  not at all" true starting from Phase 1, even though Phase 1 has no
  multi-repository transaction yet — it is exercised for real once
  `ExecutionService` (Phase 8) needs it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class SessionScopedRepository:
    """Mixin: give a repository implementation session-per-call semantics,
    upgradeable to session-per-transaction via `transaction()`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False, future=True
        )
        self._local = threading.local()

    def _active_session(self) -> Session | None:
        return getattr(self._local, "session", None)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """All writes inside the block commit together or not at all."""
        if self._active_session() is not None:
            # Already inside an outer transaction() on this instance — a
            # nested call joins it rather than opening a second one.
            yield
            return

        session = self._session_factory()
        self._local.session = session
        try:
            yield
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            self._local.session = None

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """The session one repository method should use: the shared
        transaction's session if one is open, otherwise a private
        open-commit-close session for just this call."""
        active = self._active_session()
        if active is not None:
            yield active
            return

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
