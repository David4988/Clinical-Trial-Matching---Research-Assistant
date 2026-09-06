"""`investigate(obligation, facade, provider, now) -> InvestigationRun`.

The one structured reasoning call. Implements the fallback chain exactly as
specified (`docs/FINAL_IMPLEMENTATION_PLAN.md` §12.6):

    configured provider
        ├── success + schema-valid           -> use it, degraded = false
        ├── unreachable at STARTUP           -> handled upstream, in
        │                                       agent/model/factory.py (logged once)
        ├── timeout / connection / HTTP error -> TemplateProvider, THIS request
        └── responded but schema-invalid     -> ONE repair attempt, then
                                                 TemplateProvider if still invalid

`InvestigationOutput` has no field capable of holding a decision, a
recipient, a status, or a priority (§12.2) — `escalation_number` is emitted
by the model but is advisory only; the caller overwrites it with the
ledger's actual count before use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError

from .evidence import assemble_evidence_pack, render_user_content
from .facade import TrialReadFacade
from .model.provider import AgentModelProvider, ModelRequest, ModelResult
from .model.template_provider import TemplateProvider
from .prompts import PROMPT_VERSION, REPAIR_INSTRUCTION, SYSTEM_PROMPT
from ..schema.obligations import Obligation


class InvestigationOutput(BaseModel):
    """What the model is allowed to produce. No status, verdict, recipient,
    or priority field exists on this type — see §12.2's structural argument."""

    subject: str
    body: str
    reason: str
    unresolved: list[str] = Field(default_factory=list)
    #: Advisory only. Overwritten by `Obligation.escalation_count` before
    #: this ever reaches a `ProposedAction` — never trusted as-is.
    escalation_number: int = 0


@dataclass
class InvestigationRun:
    output: InvestigationOutput
    result: ModelResult
    used_fallback: bool
    fallback_reason: str | None
    tools_called: list[str]
    evidence_ids: list[str]


def investigate(
    obligation: Obligation,
    facade: TrialReadFacade,
    provider: AgentModelProvider,
    now: datetime | None = None,
) -> InvestigationRun:
    now = now or datetime.now(timezone.utc)
    pack = assemble_evidence_pack(obligation, facade)
    user_content = render_user_content(pack)
    evidence_ids = [e.locator for e in obligation.evidence if e.locator] or [obligation.requirement_ref]

    base_request = ModelRequest(
        system_prompt=SYSTEM_PROMPT,
        user_content=user_content,
        prompt_version=PROMPT_VERSION,
        schema_name="InvestigationOutput",
        context={"obligation": obligation.model_dump(mode="json")},
    )

    first = provider.generate(base_request, InvestigationOutput, now)
    output = _validate(first)
    if output is not None:
        return InvestigationRun(
            output=_finalize(output, obligation),
            result=first,
            used_fallback=False,
            fallback_reason=None,
            tools_called=pack.tools_called,
            evidence_ids=evidence_ids,
        )

    # Connection/timeout/transport failure: no text came back at all — go
    # straight to the template floor, no repair attempt (repairing a dead
    # connection cannot help).
    if first.raw_text is None and first.parsed is None:
        return _fallback(base_request, obligation, pack, evidence_ids, now, reason=first.error or "PROVIDER_UNAVAILABLE")

    # The provider responded, but the content did not validate — one repair
    # attempt with an explicit correction instruction.
    repair_request = base_request.model_copy(
        update={"user_content": f"{user_content}\n\n{REPAIR_INSTRUCTION}\n\nYour previous response was:\n{first.raw_text}"}
    )
    second = provider.generate(repair_request, InvestigationOutput, now)
    output = _validate(second)
    if output is not None:
        return InvestigationRun(
            output=_finalize(output, obligation),
            result=second,
            used_fallback=False,
            fallback_reason=None,
            tools_called=pack.tools_called,
            evidence_ids=evidence_ids,
        )

    return _fallback(
        base_request, obligation, pack, evidence_ids, now,
        reason=second.error or "SCHEMA_INVALID_AFTER_REPAIR",
    )


def _validate(result: ModelResult) -> InvestigationOutput | None:
    if result.parsed is None:
        return None
    try:
        return InvestigationOutput.model_validate(result.parsed)
    except ValidationError:
        return None


def _finalize(output: InvestigationOutput, obligation: Obligation) -> InvestigationOutput:
    # The model's escalation_number is advisory only — always overwritten.
    return output.model_copy(update={"escalation_number": obligation.escalation_count})


def _fallback(
    base_request: ModelRequest,
    obligation: Obligation,
    pack,
    evidence_ids: list[str],
    now: datetime,
    reason: str,
) -> InvestigationRun:
    template = TemplateProvider()
    template_result = template.generate(base_request, InvestigationOutput, now)
    output = _validate(template_result)
    assert output is not None, "TemplateProvider must never fail schema validation"
    output = _finalize(output.model_copy(update={"unresolved": [*output.unresolved, reason]}), obligation)
    return InvestigationRun(
        output=output,
        result=template_result,
        used_fallback=True,
        fallback_reason=reason,
        tools_called=pack.tools_called,
        evidence_ids=evidence_ids,
    )
