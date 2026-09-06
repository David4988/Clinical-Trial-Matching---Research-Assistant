"""LIVE test against the real Ollama endpoint — Mac -> SSH tunnel -> Ollama
-> qwen3.5:9b. Skips (never fails) unless explicitly opted into, so
`pytest tests -q` stays network-free by default, matching every other
live/DB-dependent test in this suite (`tests/db_support.py`'s pattern).

Opt in with either:

    RUN_LIVE_LOCAL_MODEL_TESTS=1 pytest tests/test_agent_local_provider_live.py -q -s

or by having the default endpoint actually reachable, in which case it
still only runs — never required — mirroring `test_postgres_chosen_when_reachable`.
The real end-to-end investigation walk (screening -> obligation -> evidence
pack -> LocalProvider -> InvestigationOutput) is exercised in
`scripts/verify_local_model.py`, which prints full latency/size measurements
for manual inspection and is never collected by pytest at all.
"""

from __future__ import annotations

import os

import pytest

from app.agent.model.factory import DEFAULT_LOCAL_ENDPOINT, DEFAULT_LOCAL_MODEL_NAME
from app.agent.model.local_provider import LocalProvider
from app.agent.investigate import InvestigationOutput
from app.agent.model.provider import ModelRequest


def _require_live_ollama() -> LocalProvider:
    """Opt-in ONLY. Unlike the Postgres live tests (which run automatically
    whenever a local dev database happens to be up), this one must never run
    just because the endpoint happens to be reachable — a real LLM call is
    slow and its output is non-deterministic, so it stays out of
    `pytest tests -q` unconditionally unless a human explicitly asks for it."""
    if os.environ.get("RUN_LIVE_LOCAL_MODEL_TESTS", "").strip() != "1":
        pytest.skip(
            "Live/manual test — set RUN_LIVE_LOCAL_MODEL_TESTS=1 to run it "
            f"against a real Ollama endpoint (default {DEFAULT_LOCAL_ENDPOINT})."
        )
    provider = LocalProvider(endpoint=DEFAULT_LOCAL_ENDPOINT, model_name=DEFAULT_LOCAL_MODEL_NAME, timeout_seconds=90.0)
    if not provider.probe():
        pytest.skip(f"RUN_LIVE_LOCAL_MODEL_TESTS=1 was set but {DEFAULT_LOCAL_ENDPOINT} is not reachable.")
    return provider


def test_live_ollama_connectivity_and_thinking_disabled():
    provider = _require_live_ollama()
    request = ModelRequest(
        system_prompt="Reply with exactly one short sentence and nothing else.",
        user_content="Reply with exactly: TrialGuard local model works",
        prompt_version="v1",
        schema_name="InvestigationOutput",
    )
    import datetime

    result = provider.generate(request, InvestigationOutput, datetime.datetime.now(datetime.timezone.utc))

    assert result.degraded is False, result.error
    assert result.raw_text is not None
    assert "<think>" not in result.raw_text  # the hard switch actually worked, not just the prompt
    assert result.parsed is not None
    output = InvestigationOutput.model_validate(result.parsed)
    assert output.subject
