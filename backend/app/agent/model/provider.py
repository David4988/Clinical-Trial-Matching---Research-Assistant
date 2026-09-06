"""`AgentModelProvider` — the abstraction the rest of TrialGuard sees instead
of Ollama, llama-server, or Gemini. `docs/FINAL_IMPLEMENTATION_PLAN.md` §12.3.

One schema-driven method, not three: drafting is a field of the structured
output, not a separate call. `schema` is passed as the Pydantic class so a
provider can constrain generation *and* the caller can validate the
returned text on our side — validation is what makes malformed output safe,
regardless of which provider answered.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ...schema.obligation_enums import ProviderKind


class ModelRequest(BaseModel):
    system_prompt: str
    user_content: str
    prompt_version: str
    schema_name: str
    max_output_tokens: int = 800
    temperature: float = 0.3
    #: Structured context a provider MAY use instead of re-parsing prose —
    #: `TemplateProvider` reads `context["obligation"]` here rather than
    #: attempting to extract fields back out of `user_content`. Real model
    #: providers (Local/Hosted) ignore this; they only ever see the prompt
    #: text, exactly like the plan's `ModelRequest` describes. Additive
    #: relative to the plan's illustrative snippet — the repository's own
    #: convention throughout is that adding a member is not a breaking change.
    context: dict[str, Any] = Field(default_factory=dict)


class ModelResult(BaseModel):
    """What came back. NEVER an exception — the provider absorbs failure,
    mirroring `NotificationDeliveryProvider.deliver`'s must-never-raise
    contract."""

    raw_text: str | None = None
    parsed: dict[str, Any] | None = None
    degraded: bool = False
    error: str | None = None
    provider_name: str
    provider_kind: ProviderKind
    model_name: str
    prompt_version: str
    latency_ms: int


class AgentModelProvider(ABC):
    name: str = "abstract"
    kind: ProviderKind = ProviderKind.TEMPLATE
    model_name: str = ""
    supports_structured_output: bool = False
    supports_tool_calls: bool = False
    timeout_seconds: float = 90.0

    @abstractmethod
    def generate(self, request: ModelRequest, schema: type[BaseModel], now: datetime) -> ModelResult:
        """MUST NOT raise. Returns a `ModelResult` describing exactly what
        happened — success, a schema-invalid response, a timeout, or an
        unreachable endpoint — so the caller can decide whether to retry or
        fall back without ever catching an exception from a provider."""
        raise NotImplementedError
