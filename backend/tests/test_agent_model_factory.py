"""`agent/model/factory.py` — provider selection. Network-free: the `local`
branch is tested against a monkeypatched `LocalProvider.probe`, never a real
endpoint."""

from __future__ import annotations

from app.agent.model.factory import build_model_provider
from app.agent.model.local_provider import LocalProvider
from app.agent.model.template_provider import TemplateProvider


def test_default_is_template_with_no_env(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    assert isinstance(build_model_provider(), TemplateProvider)


def test_explicit_template():
    assert isinstance(build_model_provider(name="template"), TemplateProvider)


def test_unknown_value_falls_back_to_template(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "not-a-real-provider")
    assert isinstance(build_model_provider(), TemplateProvider)


def test_local_falls_back_to_template_when_unreachable(monkeypatch):
    monkeypatch.setattr(LocalProvider, "probe", lambda self: False)
    provider = build_model_provider(name="local")
    assert isinstance(provider, TemplateProvider)


def test_local_selected_when_reachable(monkeypatch):
    monkeypatch.setattr(LocalProvider, "probe", lambda self: True)
    provider = build_model_provider(name="local")
    assert isinstance(provider, LocalProvider)


def test_local_reads_endpoint_and_model_name_from_env(monkeypatch):
    monkeypatch.setenv("LOCAL_MODEL_ENDPOINT", "http://example.internal:11434")
    monkeypatch.setenv("LOCAL_MODEL_NAME", "some-other-model")
    monkeypatch.setattr(LocalProvider, "probe", lambda self: True)
    provider = build_model_provider(name="local")
    assert isinstance(provider, LocalProvider)
    assert provider.endpoint == "http://example.internal:11434"
    assert provider.model_name == "some-other-model"


def test_hosted_falls_back_to_template_when_not_built(monkeypatch):
    # hosted_provider.py is not implemented in this pass — the factory must
    # not raise or crash the app.
    provider = build_model_provider(name="hosted")
    assert isinstance(provider, TemplateProvider)
