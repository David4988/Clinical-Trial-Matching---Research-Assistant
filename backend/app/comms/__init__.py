"""Communication providers. `docs/FINAL_IMPLEMENTATION_PLAN.md` §16.

Imports only `schema/` and `monitoring/notifications.py` (for the ABC). The
obligation engine never imports this package — it receives a provider from
`comms/factory.py::build_delivery_provider(channel)`.
"""
