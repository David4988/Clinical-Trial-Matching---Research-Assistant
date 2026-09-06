"""The JSON implementations' `transaction()` primitive.

Deliberately not imported from `app/db/session.py`: that package imports
SQLAlchemy, and the JSON repositories must remain the zero-dependency
fallback path — see `docs/FINAL_IMPLEMENTATION_PLAN.md` §11.5. This module
has no import beyond the standard library.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext


def json_transaction() -> AbstractContextManager[None]:
    """No atomicity, explicitly — the JSON store offers none."""
    return nullcontext()
