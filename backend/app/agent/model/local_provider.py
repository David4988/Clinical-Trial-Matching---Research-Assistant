"""`LocalProvider` — talks to a locally-run model server over HTTP.

`docs/FINAL_IMPLEMENTATION_PLAN.md` §13 specified `llama-server`'s OpenAI-
compatible `/v1/chat/completions`. The actual verified local environment for
this pass runs **Ollama** instead (`http://127.0.0.1:11434`, model
`qwen3.5:9b`) — adapted here per the plan's own instruction (§12.3: "if the
Ollama API behaviour differs from the earlier llama-server plan, adapt the
provider implementation while preserving the same `AgentModelProvider`
contract"). Nothing outside this file knows Ollama exists.

Uses `httpx`, already a dependency — no new inference library. TrialGuard
never spawns, supervises, or installs anything here; Ollama is a separate
process reached over HTTP, exactly like `llama-server` would have been.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime

import httpx
from pydantic import BaseModel

from .provider import AgentModelProvider, ModelRequest, ModelResult
from ...schema.obligation_enums import ProviderKind

logger = logging.getLogger("app.agent.model.local_provider")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LocalProvider(AgentModelProvider):
    """Ollama's `/api/generate` endpoint. Non-streaming, thinking disabled
    via the runtime's own `think` flag (not a prompt instruction — a prompt
    edit cannot silently re-enable it), structured output constrained via
    the `format` JSON-schema parameter and *always* re-validated with
    Pydantic on our side regardless of what the constraint enforced."""

    kind = ProviderKind.LOCAL
    supports_structured_output = True
    supports_tool_calls = False

    def __init__(self, endpoint: str, model_name: str, timeout_seconds: float = 90.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.name = f"ollama:{model_name}"

    def probe(self) -> bool:
        """Startup-only reachability check — mirrors
        `synthetic_ml_provider`'s artifact touch and `repository/factory.py`'s
        `_probe(engine)`. Never raises; returns whether the endpoint answered."""
        try:
            response = httpx.get(f"{self.endpoint}/api/tags", timeout=5.0)
            response.raise_for_status()
            return True
        except (httpx.HTTPError, httpx.TimeoutException):
            return False

    def generate(self, request: ModelRequest, schema: type[BaseModel], now: datetime) -> ModelResult:
        payload = {
            "model": self.model_name,
            "system": request.system_prompt,
            "prompt": request.user_content,
            "think": False,
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }

        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            return self._failure(request, started, f"TIMEOUT: {exc}")
        except httpx.HTTPError as exc:
            return self._failure(request, started, f"CONNECTION_FAILED: {exc}")

        latency_ms = int((time.monotonic() - started) * 1000)

        try:
            body = response.json()
            raw_text = body.get("response")
        except (json.JSONDecodeError, ValueError) as exc:
            return self._failure(request, started, f"INVALID_RESPONSE_ENVELOPE: {exc}")

        if raw_text is None:
            return self._failure(request, started, "EMPTY_RESPONSE")

        cleaned, leaked_think = _strip_think_block(raw_text)
        if leaked_think:
            # `think: false` should make this unreachable. Reaching it means
            # the runtime or model ignored the hard switch — a configuration
            # problem worth knowing about, not a silent recovery.
            logger.error(
                "LocalProvider: a <think> block leaked into the response from "
                "%s despite think=false; stripped before parsing.",
                self.model_name,
            )

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return ModelResult(
                raw_text=raw_text,
                parsed=None,
                degraded=True,
                error="INVALID_JSON",
                provider_name=self.name,
                provider_kind=self.kind,
                model_name=self.model_name,
                prompt_version=request.prompt_version,
                latency_ms=latency_ms,
            )

        return ModelResult(
            raw_text=raw_text,
            parsed=parsed if isinstance(parsed, dict) else None,
            degraded=not isinstance(parsed, dict),
            error=None if isinstance(parsed, dict) else "NON_OBJECT_JSON",
            provider_name=self.name,
            provider_kind=self.kind,
            model_name=self.model_name,
            prompt_version=request.prompt_version,
            latency_ms=latency_ms,
        )

    def _failure(self, request: ModelRequest, started: float, error: str) -> ModelResult:
        latency_ms = int((time.monotonic() - started) * 1000)
        return ModelResult(
            raw_text=None,
            parsed=None,
            degraded=True,
            error=error,
            provider_name=self.name,
            provider_kind=self.kind,
            model_name=self.model_name,
            prompt_version=request.prompt_version,
            latency_ms=latency_ms,
        )


def _strip_think_block(text: str) -> tuple[str, bool]:
    stripped = _THINK_BLOCK.sub("", text).strip()
    return stripped, stripped != text.strip()
