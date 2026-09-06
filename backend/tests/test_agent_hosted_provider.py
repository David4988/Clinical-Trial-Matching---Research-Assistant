"""`HostedProvider` — network-free. `genai.Client(api_key=...)` never makes a
network call at construction, so a fake key is safe here; every call the
provider itself makes is monkeypatched onto the client's `.models` object.
"""

from __future__ import annotations

import json as json_module
from datetime import datetime, timezone
from types import SimpleNamespace

from app.agent.investigate import InvestigationOutput
from app.agent.model.hosted_provider import HostedProvider
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


def _provider() -> HostedProvider:
    return HostedProvider(api_key="fake-key", model_name="gemini-3.6-flash", timeout_seconds=5.0)


def test_successful_response_validates(monkeypatch):
    body = json_module.dumps({"subject": "s", "body": "b", "reason": "r"})

    def fake_generate_content(model, contents, config):
        assert model == "gemini-3.6-flash"
        assert config.response_mime_type == "application/json"
        return SimpleNamespace(text=body)

    provider = _provider()
    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate_content)
    result = provider.generate(_request(), InvestigationOutput, NOW)

    assert result.degraded is False
    assert result.provider_kind is ProviderKind.HOSTED
    assert result.parsed == {"subject": "s", "body": "b", "reason": "r"}
    InvestigationOutput.model_validate(result.parsed)


def test_malformed_json_is_reported_degraded(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        provider._client.models, "generate_content",
        lambda model, contents, config: SimpleNamespace(text="not json {"),
    )
    result = provider.generate(_request(), InvestigationOutput, NOW)
    assert result.degraded is True
    assert result.error == "INVALID_JSON"


def test_empty_response_is_a_failure(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        provider._client.models, "generate_content",
        lambda model, contents, config: SimpleNamespace(text=None),
    )
    result = provider.generate(_request(), InvestigationOutput, NOW)
    assert result.degraded is True
    assert result.error == "EMPTY_RESPONSE"


def test_api_error_never_raises(monkeypatch):
    def fake_generate_content(model, contents, config):
        raise RuntimeError("503 Service Unavailable")

    provider = _provider()
    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate_content)
    result = provider.generate(_request(), InvestigationOutput, NOW)
    assert result.degraded is True
    assert "HOSTED_API_ERROR" in result.error


def test_timeout_is_classified_distinctly(monkeypatch):
    def fake_generate_content(model, contents, config):
        raise TimeoutError("Deadline exceeded while waiting for response")

    provider = _provider()
    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate_content)
    result = provider.generate(_request(), InvestigationOutput, NOW)
    assert result.degraded is True
    assert "TIMEOUT" in result.error


def test_model_not_found_is_classified_distinctly(monkeypatch):
    def fake_generate_content(model, contents, config):
        raise RuntimeError("404 NOT_FOUND. Model is not found: models/bogus")

    provider = _provider()
    monkeypatch.setattr(provider._client.models, "generate_content", fake_generate_content)
    result = provider.generate(_request(), InvestigationOutput, NOW)
    assert "MODEL_NOT_FOUND" in result.error


def test_probe_true_when_model_exists(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(provider._client.models, "get", lambda model: SimpleNamespace(name=model))
    assert provider.probe() is True


def test_probe_false_and_logs_the_real_error_when_model_is_invalid(monkeypatch, caplog):
    def fake_get(model):
        raise RuntimeError("404 NOT_FOUND. Model is not found: models/typo-d-name")

    provider = _provider()
    monkeypatch.setattr(provider._client.models, "get", fake_get)
    with caplog.at_level("ERROR"):
        assert provider.probe() is False
    assert "typo-d-name" in caplog.text  # the SPECIFIC error, not a generic message
