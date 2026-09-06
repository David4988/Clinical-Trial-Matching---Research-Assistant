"""The obligation layer — detection, lifecycle, ledger, queue, proposals and
execution. See `docs/FINAL_IMPLEMENTATION_PLAN.md` §4-§8, §20.

Module boundary (checkable the same way as `ARCHITECTURE.md`'s table):
`obligations/` imports `schema/`, `repository/`, and `monitoring/` (for
`ids`-style helpers only). `obligations/detectors/` imports `schema/` only —
pure functions, no I/O.
"""
