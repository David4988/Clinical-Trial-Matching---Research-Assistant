"""`HostedProvider` — Gemini via `google-genai`, already a dependency
(`docs/FINAL_IMPLEMENTATION_PLAN.md` §14; the client construction mirrors
`risk/xai_client.py`, the existing Gemini caller in this repository).

Nothing outside this file knows Gemini exists. `google-genai` accepts a
Pydantic class directly as `response_schema` and auto-validates into
`.parsed` — used here as a first pass, but the raw JSON text is still
independently re-parsed and handed back as `parsed: dict`, because
`agent/investigate.py` — not this provider — owns the authoritative
Pydantic validation step, exactly as it does for `LocalProvider`.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from google import genai
from google.genai import types
from pydantic import BaseModel

from .provider import AgentModelProvider, ModelRequest, ModelResult
from ...schema.obligation_enums import ProviderKind

logger = logging.getLogger("app.agent.model.hosted_provider")


class HostedProvider(AgentModelProvider):
    kind = ProviderKind.HOSTED
    supports_structured_output = True
    supports_tool_calls = False

    def __init__(self, api_key: str, model_name: str, timeout_seconds: float = 90.0) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.name = f"gemini:{model_name}"
        self._client = genai.Client(
            api_key=api_key,
            http_options={"timeout": int(timeout_seconds * 1000)},
        )

    def probe(self) -> bool:
        """Verifies the CONFIGURED model id actually exists against the live
        API — a typo'd model name must be a loud, specific log line, never
        silently reported as generic 'AI unavailable'."""
        try:
            self._client.models.get(model=self.model_name)
            return True
        except Exception as exc:  # noqa: BLE001 - startup probe, never raises
            logger.error(
                "Hosted model probe failed for model=%r: %s", self.model_name, exc
            )
            return False

    def generate(self, request: ModelRequest, schema: type[BaseModel], now: datetime) -> ModelResult:
        started = time.monotonic()
        try:
            response = self._client.models.generate_content(
                model=self.model_name,
                contents=request.user_content,
                config=types.GenerateContentConfig(
                    system_instruction=request.system_prompt,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=request.temperature,
                    max_output_tokens=request.max_output_tokens,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - provider must never raise
            message = str(exc)
            if "timeout" in message.lower() or "deadline" in message.lower():
                return self._failure(request, started, f"TIMEOUT: {message}")
            if "NOT_FOUND" in message or "404" in message:
                return self._failure(request, started, f"MODEL_NOT_FOUND: {message}")
            return self._failure(request, started, f"HOSTED_API_ERROR: {message}")

        latency_ms = int((time.monotonic() - started) * 1000)
        raw_text = response.text
        if raw_text is None:
            return self._failure(request, started, "EMPTY_RESPONSE")

        try:
            parsed = json.loads(raw_text)
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
