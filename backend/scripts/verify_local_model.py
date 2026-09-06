"""LIVE / MANUAL verification of the real Ollama endpoint. NOT part of the
default `pytest tests -q` suite — this file lives in `scripts/`, not
`tests/`, specifically so it is never collected by pytest.

Run manually, with the SSH tunnel to the PC's Ollama instance up:

    python scripts/verify_local_model.py

Exercises two things in order:

1. A trivial prompt, to measure baseline latency.
2. The REAL TrialGuard investigation path for the CT-001 / P-3311 / INC-04
   missing-eGFR obligation — the same `agent.investigate()` call
   `obligations/proposals.py` makes, against a real obligation built from
   the real fixtures and a real screening run.

Prints prompt/output sizes, latency, and the resulting `InvestigationOutput`
so a human can eyeball it before trusting the provider in a demo.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent.facade import TrialReadFacade  # noqa: E402
from app.agent.investigate import InvestigationOutput, investigate  # noqa: E402
from app.agent.model.local_provider import LocalProvider  # noqa: E402
from app.agent.model.provider import ModelRequest  # noqa: E402
from app.fixtures_loader import load_parties, load_patient, load_trial  # noqa: E402
from app.obligations import reconcile as reconcile_module  # noqa: E402
from app.obligations.detectors import missing_lab  # noqa: E402
from app.repository.json_obligations import JsonObligationRepository  # noqa: E402
from app.repository.json_repo import JsonRepository  # noqa: E402
from app.schema.result import ScreeningResult  # noqa: E402
from app.service import ScreeningService  # noqa: E402

ENDPOINT = "http://127.0.0.1:11434"
MODEL_NAME = "qwen3.5:9b"


def _hr(title: str) -> None:
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def check_connectivity(provider: LocalProvider) -> None:
    _hr("1. Connectivity")
    reachable = provider.probe()
    print(f"Endpoint: {provider.endpoint}")
    print(f"Model:    {provider.model_name}")
    print(f"Reachable: {reachable}")
    if not reachable:
        print("FAILED — is the SSH tunnel to the PC's Ollama instance up?")
        sys.exit(1)


def small_prompt_latency(provider: LocalProvider) -> None:
    _hr("2. Small prompt latency")
    request = ModelRequest(
        system_prompt="Reply with exactly one short sentence.",
        user_content="Reply with exactly: TrialGuard local model works",
        prompt_version="v1",
        schema_name="_TrivialCheck",
    )

    started = time.monotonic()
    result = provider.generate(request, InvestigationOutput, datetime.now(timezone.utc))
    elapsed = time.monotonic() - started
    print(f"Prompt size (chars): {len(request.system_prompt) + len(request.user_content)}")
    print(f"Output size (chars): {len(result.raw_text or '')}")
    print(f"Latency: {elapsed:.2f}s (provider-reported {result.latency_ms}ms)")
    print(f"Degraded: {result.degraded}  Error: {result.error}")
    print(f"Raw text: {result.raw_text!r}")


def real_investigation(provider: LocalProvider) -> None:
    _hr("3. Real TrialGuard investigation: CT-001 / P-3311 / INC-04")

    patient = load_patient("patient_incomplete")
    trial = load_trial("trial_demo")

    service = ScreeningService(repository=JsonRepository(ROOT / "data" / "_verify_store.json"))
    result: ScreeningResult = service.screen(patient, trial)
    print(f"Screening overall_status: {result.overall_status.value}")

    obligation_repo = JsonObligationRepository(ROOT / "data" / "_verify_obligations.json")
    for party in load_parties():
        obligation_repo.save_party(party)

    detected = missing_lab.detect(result)
    assert detected, "The fixture no longer produces a missing-eGFR gap — check fixtures/trial_demo.json"

    now = datetime.now(timezone.utc)
    delta = reconcile_module.reconcile(
        trial_id=result.trial.trial_id,
        patient_id=result.patient.patient_id,
        detector_source="SCREENING",
        detected=detected,
        existing=[],
        now=now,
    )
    obligation = delta.created[0]
    obligation_repo.save_obligation(obligation)
    obligation_repo.append_actions(delta.created_actions)
    print(f"Obligation: {obligation.obligation_id} — {obligation.title}")

    facade = TrialReadFacade(obligation_repo, service.repository)

    from app.agent.evidence import assemble_evidence_pack, render_user_content
    from app.agent.prompts import SYSTEM_PROMPT

    pack = assemble_evidence_pack(obligation, facade)
    user_content = render_user_content(pack)
    prompt_chars = len(SYSTEM_PROMPT) + len(user_content)

    started = time.monotonic()
    run = investigate(obligation, facade, provider, now)
    elapsed = time.monotonic() - started

    print(f"\nEvidence-pack prompt size (chars): {prompt_chars}")
    print(f"Output size (chars): {len(run.result.raw_text or '')}")
    print(f"Latency: {elapsed:.2f}s (provider-reported {run.result.latency_ms}ms)")
    print(f"Tools called (fixed order): {run.tools_called}")
    print(f"Used fallback: {run.used_fallback}  Reason: {run.fallback_reason}")
    print(f"Provider kind: {run.result.provider_kind.value}  Model: {run.result.model_name}")
    print("\n--- InvestigationOutput ---")
    print(json.dumps(run.output.model_dump(mode="json"), indent=2))

    assert not run.used_fallback, "Expected the real local model to answer, not the TemplateProvider fallback"
    print("\nOK: the real local model produced a schema-valid InvestigationOutput.")


def main() -> None:
    provider = LocalProvider(endpoint=ENDPOINT, model_name=MODEL_NAME, timeout_seconds=90.0)
    check_connectivity(provider)
    small_prompt_latency(provider)
    real_investigation(provider)


if __name__ == "__main__":
    main()
