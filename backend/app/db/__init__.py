"""SQLAlchemy Core access layer for PostgreSQL persistence.

This is the only package in the application that imports SQLAlchemy.
`repository/sql_repo.py` and `repository/sql_monitoring.py` are the only
consumers, and they hold no other reference to a session or an engine than
what this package hands them. See `docs/FINAL_IMPLEMENTATION_PLAN.md` §9.8.
"""
