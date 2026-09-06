"""`agent/investigate.py` — the fallback chain, tested against fake
providers so it never depends on a real model. `docs/FINAL_IMPLEMENTATION_PLAN.md`
§12.6."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agent.investigate import InvestigationOutput, investigate
from app.agent.model.provider import AgentModelProvider, ModelRequest, ModelResult
from app.schema.clinical import Evidence
from app.schema.obligation_enums import (
    ObligationPriority,
    ObligationStatus,
    ObligationType,
    ProviderKind,
)
from app.schema.obligations import Obligation

NOW = datetime.now(timezone.utc)


class FakeFacade:
    def get_ledger(self, obligation_id):
        return []

    def get_screening_result(self, result_id):
        return None

    def get_party(self, party_id):
        return None


def _obligation() -> Obligation:
    return Obligation(
        obligation_id="OB-1",
        obligation_key="CT-001|P-3311|MISSING_LAB_EVIDENCE|INC-04|",
        trial_id="CT-001",
        patient_id="P-3311",
        type=ObligationType.MISSING_LAB_EVIDENCE,
        status=ObligationStatus.OPEN,
        priority=ObligationPriority.LOW,
        requirement_ref="INC-04",
        requirement_text="eGFR at least 45 mL/min",
        protocol_id="CT-001",
        source_ref="SR-1",
        detector_source="SCREENING",
        title="t",
        detail="d",
        evidence=[Evidence(source_type="RULE", locator="INC-04", snippet="s", note=None)],
        first_detected_at=NOW,
        last_confirmed_at=NOW,
        escalation_count=2,
    )


class ScriptedProvider(AgentModelProvider):
    """Returns a fixed sequence of ModelResults, one per call."""

    kind = ProviderKind.LOCAL
    model_name = "fake-model"

    def __init__(self, results: list[ModelResult]) -> None:
        self.name = "fake"
        self._results = list(results)
        self.calls: list[ModelRequest] = []

    def generate(self, request: ModelRequest, schema, now):
        self.calls.append(request)
        return self._results.pop(0)


def _result(parsed=None, raw_text=None, error=None, degraded=False) -> ModelResult:
    return ModelResult(
        raw_text=raw_text,
        parsed=parsed,
        degraded=degraded,
        error=error,
        provider_name="fake",
        provider_kind=ProviderKind.LOCAL,
        model_name="fake-model",
        prompt_version="v1",
        latency_ms=123,
    )


def test_successful_first_attempt_is_used_directly():
    provider = ScriptedProvider([_result(parsed={"subject": "s", "body": "b", "reason": "r"})])
    run = investigate(_obligation(), FakeFacade(), provider, NOW)
    assert run.used_fallback is False
    assert run.output.subject == "s"
    assert len(provider.calls) == 1


def test_escalation_number_is_always_overwritten_by_ledger_count():
    provider = ScriptedProvider(
        [_result(parsed={"subject": "s", "body": "b", "reason": "r", "escalation_number": 999})]
    )
    run = investigate(_obligation(), FakeFacade(), provider, NOW)
    assert run.output.escalation_number == 2  # obligation.escalation_count, never the model's 999


def test_connection_failure_skips_repair_and_falls_back_immediately():
    provider = ScriptedProvider([_result(error="CONNECTION_FAILED: refused", degraded=True)])
    run = investigate(_obligation(), FakeFacade(), provider, NOW)
    assert run.used_fallback is True
    assert "CONNECTION_FAILED" in run.fallback_reason
    assert len(provider.calls) == 1  # no repair attempt for a transport failure
    assert run.output.subject  # TemplateProvider still produced a usable draft


def test_schema_invalid_gets_one_repair_attempt_then_succeeds():
    provider = ScriptedProvider(
        [
            _result(raw_text="not valid json", parsed=None, error="INVALID_JSON", degraded=True),
            _result(parsed={"subject": "s2", "body": "b2", "reason": "r2"}),
        ]
    )
    run = investigate(_obligation(), FakeFacade(), provider, NOW)
    assert run.used_fallback is False
    assert run.output.subject == "s2"
    assert len(provider.calls) == 2


def test_schema_invalid_after_repair_falls_back_to_template():
    provider = ScriptedProvider(
        [
            _result(raw_text="bad", parsed=None, error="INVALID_JSON", degraded=True),
            _result(parsed={"wrong": "shape"}),  # valid JSON, still schema-invalid
        ]
    )
    run = investigate(_obligation(), FakeFacade(), provider, NOW)
    assert run.used_fallback is True
    assert run.fallback_reason == "SCHEMA_INVALID_AFTER_REPAIR"
    assert len(provider.calls) == 2
    assert run.output.subject  # still a usable draft


def test_provider_never_raises_even_when_investigate_wraps_it():
    # A provider that behaves per its own contract (never raises) means
    # investigate() never needs a try/except around generate() itself.
    provider = ScriptedProvider([_result(error="TIMEOUT: slow", degraded=True)])
    run = investigate(_obligation(), FakeFacade(), provider, NOW)
    assert run.used_fallback is True
    assert run.result.provider_kind is ProviderKind.TEMPLATE
