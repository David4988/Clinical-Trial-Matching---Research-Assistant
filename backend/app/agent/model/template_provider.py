"""`TemplateProvider` — a normal `AgentModelProvider` implementation, not an
exception-only fallback branch (`docs/FINAL_IMPLEMENTATION_PLAN.md` §12.4).

Delegates all text generation to `obligations/templates.py`, the single
deterministic drafting module. This class only adapts that module's output
into the `AgentModelProvider` shape. It never degrades — it has no
dependency to lose — which is what makes the bottom of the fallback chain a
floor rather than another failure mode.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .provider import AgentModelProvider, ModelRequest, ModelResult
from ...obligations import templates
from ...schema.obligation_enums import ProviderKind
from ...schema.obligations import Obligation


class TemplateProvider(AgentModelProvider):
    name = "deterministic-template"
    kind = ProviderKind.TEMPLATE
    model_name = "template-v1"
    supports_structured_output = True  # trivially — it constructs the object directly
    supports_tool_calls = False
    timeout_seconds = 0.0

    def generate(self, request: ModelRequest, schema: type[BaseModel], now: datetime) -> ModelResult:
        obligation_data = request.context.get("obligation")
        obligation = Obligation.model_validate(obligation_data) if obligation_data else None

        if obligation is None:
            # Nothing to draft from — still never raises, still never
            # degrades in the ModelResult sense; the caller (agent/investigate.py)
            # is responsible for treating an empty parse as unusable.
            return ModelResult(
                raw_text=None,
                parsed=None,
                degraded=False,
                error="NO_OBLIGATION_CONTEXT",
                provider_name=self.name,
                provider_kind=self.kind,
                model_name=self.model_name,
                prompt_version=request.prompt_version,
                latency_ms=0,
            )

        parsed = {
            "subject": templates.draft_subject(obligation),
            "body": templates.draft_body(obligation),
            "reason": templates.draft_reason(obligation),
            "unresolved": [],
            "escalation_number": obligation.escalation_count,
        }
        return ModelResult(
            raw_text=None,
            parsed=parsed,
            degraded=False,
            provider_name=self.name,
            provider_kind=self.kind,
            model_name=self.model_name,
            prompt_version=request.prompt_version,
            latency_ms=0,
        )
