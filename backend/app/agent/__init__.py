"""The investigation agent. One agent, not a swarm — a fixed evidence
pipeline plus one structured reasoning call (`docs/FINAL_IMPLEMENTATION_PLAN.md`
§12.1, §12.5's `AGENT_MODE=packed`).

Module boundary, enforced structurally: `agent/` imports `schema/`,
`agent/model/`, and `agent/facade.py` — **never** `repository/`, `comms/`,
or `obligations/service.py`. `facade.py` is the one file in this package
that touches the rest of the application, and it exposes read methods only.
"""
