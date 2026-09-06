"""The primary acceptance path (`docs/FINAL_IMPLEMENTATION_PLAN.md`'s reduced
critical-path acceptance test): P-3311 / CT-001 / INC-04 / missing eGFR,
walked end-to-end through the real HTTP API, over the JSON backend."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .obligation_support import build_client

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _patient() -> dict:
    return json.loads((FIXTURES / "patient_incomplete.json").read_text())


def _trial() -> dict:
    return json.loads((FIXTURES / "trial_demo.json").read_text())


def test_missing_egfr_produces_exactly_one_obligation(tmp_path):
    client = build_client(tmp_path)
    patient, trial = _patient(), _trial()

    result = client.post("/screen", json={"patient": patient, "trial": trial}).json()
    assert result["overall_status"] == "REVIEW_REQUIRED"  # UNKNOWN on INC-04, pre-obligation-layer

    obligations = client.get("/obligations", params={"trial_id": "CT-001"}).json()
    assert obligations["count"] == 1
    obligation = obligations["obligations"][0]
    assert obligation["patient_id"] == "P-3311"
    assert obligation["requirement_ref"] == "INC-04"
    assert obligation["type"] == "MISSING_LAB_EVIDENCE"
    assert obligation["status"] == "OPEN"
    assert obligation["obligation_key"] == "CT-001|P-3311|MISSING_LAB_EVIDENCE|INC-04|"


def test_repeated_screening_does_not_duplicate(tmp_path):
    client = build_client(tmp_path)
    patient, trial = _patient(), _trial()

    for _ in range(4):
        client.post("/screen", json={"patient": patient, "trial": trial})

    obligations = client.get("/obligations", params={"trial_id": "CT-001"}).json()
    assert obligations["count"] == 1


def test_full_loop_detect_queue_propose_approve_execute_resolve(tmp_path):
    client = build_client(tmp_path)
    patient, trial = _patient(), _trial()

    client.post("/screen", json={"patient": patient, "trial": trial})

    queue = client.get("/obligations/queue", params={"trial_id": "CT-001"}).json()
    assert queue["counts"]["total"] == 1
    item = queue["items"][0]
    obligation_id = item["obligation_id"]
    assert item["needs_human_decision"] is False

    detail = client.get(f"/obligations/{obligation_id}").json()
    assert detail["requirement_text"]
    assert detail["evidence"]

    ledger = client.get(f"/obligations/{obligation_id}/actions").json()
    assert [a["kind"] for a in ledger] == ["DETECTED"]

    # investigate -> DRAFT proposal
    propose_resp = client.post(f"/obligations/{obligation_id}/investigate")
    assert propose_resp.status_code == 201
    proposal = propose_resp.json()
    assert proposal["status"] == "DRAFT"
    proposal_id = proposal["proposal_id"]

    # a second undecided proposal is refused
    duplicate = client.post(f"/obligations/{obligation_id}/investigate")
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "PROPOSAL_PENDING"

    # approval requires reviewer + note
    missing_reviewer = client.post(
        f"/obligations/proposals/{proposal_id}/approve", json={"reviewer": "", "note": "ok"}
    )
    assert missing_reviewer.status_code == 422
    assert missing_reviewer.json()["error"]["code"] == "REVIEWER_REQUIRED"

    approved = client.post(
        f"/obligations/proposals/{proposal_id}/approve",
        json={"reviewer": "Dr. Rao", "note": "Reviewed and accurate."},
    )
    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["status"] == "EXECUTED"
    assert approved_body["execution"]["delivery_status"] == "SENT"
    assert approved_body["decision"]["reviewer"] == "Dr. Rao"

    obligation = client.get(f"/obligations/{obligation_id}").json()
    assert obligation["status"] == "AWAITING_RESPONSE"

    # re-approving the same (now decided) proposal is refused — no double send
    reapprove = client.post(
        f"/obligations/proposals/{proposal_id}/approve",
        json={"reviewer": "Dr. Rao", "note": "again"},
    )
    assert reapprove.status_code == 422
    assert reapprove.json()["error"]["code"] == "PROPOSAL_NOT_DRAFT"

    ledger_after = client.get(f"/obligations/{obligation_id}/actions").json()
    kinds = [a["kind"] for a in ledger_after]
    assert kinds == ["DETECTED", "PROPOSAL_CREATED", "MESSAGE_SENT", "PROPOSAL_APPROVED"]
    seqs = [a["seq"] for a in ledger_after]
    assert seqs == sorted(seqs) == list(range(1, len(seqs) + 1))  # strictly increasing, no gaps

    # add real eGFR evidence and re-screen -> the obligation resolves
    patient_with_egfr = copy.deepcopy(patient)
    patient_with_egfr["labs"].append(
        {"name": "eGFR", "value": 60, "unit": "mL/min", "observed_at": "2026-02-01"}
    )
    client.post("/screen", json={"patient": patient_with_egfr, "trial": trial})

    resolved = client.get(f"/obligations/{obligation_id}").json()
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"]["kind"] == "SATISFIED"
    assert resolved["resolution"]["by"] == "SYSTEM"

    # the queue for this trial is empty of open work now
    final_queue = client.get("/obligations/queue", params={"trial_id": "CT-001"}).json()
    assert all(i["obligation_id"] != obligation_id for i in final_queue["items"] if i["status"] != "RESOLVED")


def test_dismiss_requires_reviewer_and_note_and_is_terminal(tmp_path):
    client = build_client(tmp_path)
    patient, trial = _patient(), _trial()
    client.post("/screen", json={"patient": patient, "trial": trial})
    obligation_id = client.get("/obligations", params={"trial_id": "CT-001"}).json()["obligations"][0]["obligation_id"]

    refused = client.post(f"/obligations/{obligation_id}/dismiss", json={"reviewer": "Dr. Rao", "note": ""})
    assert refused.status_code == 422

    dismissed = client.post(
        f"/obligations/{obligation_id}/dismiss",
        json={"reviewer": "Dr. Rao", "note": "Not clinically relevant for this cohort."},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "DISMISSED"

    # terminal: a second dismiss is refused
    again = client.post(
        f"/obligations/{obligation_id}/dismiss", json={"reviewer": "Dr. Rao", "note": "again"}
    )
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "OBLIGATION_TERMINAL"

    # re-screening the same gap does not resurrect the dismissed row —
    # it creates a fresh obligation with the same key (§6.3: no reopening)
    client.post("/screen", json={"patient": patient, "trial": trial})
    all_obligations = client.get("/obligations", params={"trial_id": "CT-001"}).json()["obligations"]
    assert len(all_obligations) == 2
    assert {o["status"] for o in all_obligations} == {"DISMISSED", "OPEN"}
    assert len({o["obligation_id"] for o in all_obligations}) == 2
    assert all(o["obligation_key"] == "CT-001|P-3311|MISSING_LAB_EVIDENCE|INC-04|" for o in all_obligations)
