"""Choosing which model provider a deployment runs. Mirrors
`risk/factory.py` and `repository/factory.py` structurally: read the
environment once at startup, construct, probe, and on any failure log
**once** and fall back — never refuse to start over a missing or unreachable
model. `docs/FINAL_IMPLEMENTATION_PLAN.md` §12.3, §12.6.
"""

from __future__ import annotations

import logging
import os

from .provider import AgentModelProvider
from .template_provider import TemplateProvider

logger = logging.getLogger("app.agent.model.factory")

TEMPLATE = "template"
LOCAL = "local"
HOSTED = "hosted"

PROVIDER_NAMES = (TEMPLATE, LOCAL, HOSTED)

ENV_VAR = "MODEL_PROVIDER"
LOCAL_ENDPOINT_ENV = "LOCAL_MODEL_ENDPOINT"
LOCAL_MODEL_NAME_ENV = "LOCAL_MODEL_NAME"
AGENT_TIMEOUT_ENV = "AGENT_TIMEOUT_SECONDS"

DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_LOCAL_MODEL_NAME = "qwen3.5:9b"
DEFAULT_AGENT_TIMEOUT_SECONDS = 90.0


def agent_timeout_seconds() -> float:
    raw = os.environ.get(AGENT_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_AGENT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using the default (%s).", AGENT_TIMEOUT_ENV, raw, DEFAULT_AGENT_TIMEOUT_SECONDS)
        return DEFAULT_AGENT_TIMEOUT_SECONDS


def build_model_provider(name: str | None = None) -> AgentModelProvider:
    """Construct the named provider, falling back to `TemplateProvider` if
    it cannot be reached. Never raises — the startup probe failure is
    logged exactly once here, not on every subsequent request; a request-time
    failure is a separate, per-call concern handled in `agent/investigate.py`."""
    chosen = (name or os.environ.get(ENV_VAR) or TEMPLATE).strip().lower()

    if chosen == TEMPLATE:
        return TemplateProvider()

    if chosen == LOCAL:
        from .local_provider import LocalProvider

        endpoint = os.environ.get(LOCAL_ENDPOINT_ENV, DEFAULT_LOCAL_ENDPOINT).strip()
        model_name = os.environ.get(LOCAL_MODEL_NAME_ENV, DEFAULT_LOCAL_MODEL_NAME).strip()
        provider = LocalProvider(endpoint=endpoint, model_name=model_name, timeout_seconds=agent_timeout_seconds())
        if provider.probe():
            return provider
        logger.error(
            "Could not reach the local model endpoint %s (model=%s); "
            "falling back to the deterministic template provider for this run.",
            endpoint,
            model_name,
        )
        return TemplateProvider()

    if chosen == HOSTED:
        try:
            from .hosted_provider import HostedProvider  # not built in this pass

            return HostedProvider()
        except Exception as exc:  # noqa: BLE001 - startup must not fail here
            logger.error("Could not start the hosted model provider (%s); falling back to template.", exc)
            return TemplateProvider()

    logger.warning(
        "Unknown %s=%r; expected one of %s. Using the deterministic template provider.",
        ENV_VAR,
        chosen,
        ", ".join(PROVIDER_NAMES),
    )
    return TemplateProvider()
