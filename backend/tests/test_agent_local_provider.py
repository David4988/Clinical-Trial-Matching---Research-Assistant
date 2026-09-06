"""`LocalProvider` — network-free. Every httpx call is monkeypatched so this
file never touches a real endpoint; the live Ollama check lives in
`test_agent_local_provider_live.py`, deselected from the default suite.
"""

from __future__ import annotations

import json as json_module
from datetime import datetime, timezone

import httpx
import pytest

from app.agent.investigate import InvestigationOutput
from app.agent.model.local_provider import LocalProvider
from app.agent.model.provider import ModelRequest
from app.schema.obligation_enums import ProviderKind

NOW = datetime.now(timezone.utc)


def _request() -> ModelRequest:
    return ModelRequest(
        system_prompt="system",
        user_content="user content",
        prompt_version="v1",
        schema_name="InvestigationOutput",
    )


def _provider() -> LocalProvider:
    return LocalProvider(endpoint="http://fake-ollama:11434", model_name="qwen3.5:9b", timeout_seconds=5.0)


def test_successful_response_validates(monkeypatch):
    body = {"response": json_module.dumps({"subject": "s", "body": "b", "reason": "r"})}

    def fake_post(url, json, timeout):
        assert "/api/generate" in url
        assert json["think"] is False
        assert json["stream"] is False
        assert json["model"] == "qwen3.5:9b"
        assert "format" in json  # the JSON schema is sent
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr("app.agent.model.local_provider.httpx.post", fake_post)
    result = _provider().generate(_request(), InvestigationOutput, NOW)

    assert result.degraded is False
    assert result.error is None
    assert result.provider_kind is ProviderKind.LOCAL
    assert result.parsed == {"subject": "s", "body": "b", "reason": "r"}
    output = InvestigationOutput.model_validate(result.parsed)
    assert output.subject == "s"


def test_leaked_think_block_is_stripped(monkeypatch):
    raw = "<think>reasoning I should not see</think>" + json_module.dumps(
        {"subject": "s", "body": "b", "reason": "r"}
    )
    monkeypatch.setattr(
        "app.agent.model.local_provider.httpx.post",
        lambda url, json, timeout: httpx.Response(200, json={"response": raw}, request=httpx.Request("POST", url)),
    )
    result = _provider().generate(_request(), InvestigationOutput, NOW)
    assert result.parsed == {"subject": "s", "body": "b", "reason": "r"}


def test_malformed_json_is_reported_degraded(monkeypatch):
    monkeypatch.setattr(
        "app.agent.model.local_provider.httpx.post",
        lambda url, json, timeout: httpx.Response(200, json={"response": "not json at all {"}, request=httpx.Request("POST", url)),
    )
    result = _provider().generate(_request(), InvestigationOutput, NOW)
    assert result.degraded is True
    assert result.error == "INVALID_JSON"
    assert result.parsed is None


def test_schema_invalid_response_still_parses_as_json_but_fails_pydantic(monkeypatch):
    # Valid JSON, wrong shape (missing required fields) — the provider
    # itself reports the raw parse; Pydantic validation is the CALLER's job
    # (agent/investigate.py), never done manually here.
    monkeypatch.setattr(
        "app.agent.model.local_provider.httpx.post",
        lambda url, json, timeout: httpx.Response(200, json={"response": json_module.dumps({"unexpected": "shape"})}, request=httpx.Request("POST", url)),
    )
    result = _provider().generate(_request(), InvestigationOutput, NOW)
    assert result.parsed == {"unexpected": "shape"}
    with pytest.raises(Exception):
        InvestigationOutput.model_validate(result.parsed)


def test_timeout_never_raises(monkeypatch):
    def fake_post(url, json, timeout):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.agent.model.local_provider.httpx.post", fake_post)
    result = _provider().generate(_request(), InvestigationOutput, NOW)
    assert result.degraded is True
    assert "TIMEOUT" in result.error
    assert result.raw_text is None


def test_connection_failure_never_raises(monkeypatch):
    def fake_post(url, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.agent.model.local_provider.httpx.post", fake_post)
    result = _provider().generate(_request(), InvestigationOutput, NOW)
    assert result.degraded is True
    assert "CONNECTION_FAILED" in result.error


def test_probe_true_when_endpoint_reachable(monkeypatch):
    monkeypatch.setattr(
        "app.agent.model.local_provider.httpx.get",
        lambda url, timeout: httpx.Response(200, json={"models": []}, request=httpx.Request("GET", url)),
    )
    assert _provider().probe() is True


def test_probe_false_when_endpoint_unreachable(monkeypatch):
    def fake_get(url, timeout):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr("app.agent.model.local_provider.httpx.get", fake_get)
    assert _provider().probe() is False
