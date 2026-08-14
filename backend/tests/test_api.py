"""API-level tests, including the PDF round-trip and error envelopes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.fixtures_loader import load_patient, load_trial
from app.main import create_app
from app.repository.json_repo import JsonRepository
from app.service import ScreeningService

PDF_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"


@pytest.fixture
def client(tmp_path):
    service = ScreeningService(repository=JsonRepository(tmp_path / "store.json"))
    return TestClient(create_app(service))


def _require_pdf(name: str) -> bytes:
    path = PDF_DIR / name
    if not path.exists():
        pytest.skip(f"{name} missing — run scripts/generate_demo_pdf.py")
    return path.read_bytes()


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["ai_provider"] == "mock-slm-v1"


def test_screen_with_canonical_json(client):
    payload = {
        "patient": load_patient("patient_eligible").model_dump(mode="json"),
        "trial": load_trial("trial_supported").model_dump(mode="json"),
    }
    response = client.post("/screen", json=payload)

    assert response.status_code == 200
    assert response.json()["overall_status"] == "ELIGIBLE"


def test_screen_pdf_matches_canonical_screen(client):
    """DoD #6: both entry points reach the same verdict for the same record.

    Evidence locators legitimately differ (one cites PDF lines, the other cites
    canonical fields) — that difference is the point of the boundary. What must
    match is every decision-relevant field.
    """
    pdf_response = client.post(
        "/screen/pdf",
        files={"file": ("demo_screening.pdf", _require_pdf("demo_screening.pdf"), "application/pdf")},
    )
    assert pdf_response.status_code == 200
    from_pdf = pdf_response.json()

    json_response = client.post(
        "/screen",
        json={
            "patient": load_patient("patient_pdf_demo").model_dump(mode="json"),
            "trial": load_trial("trial_demo").model_dump(mode="json"),
        },
    )
    assert json_response.status_code == 200
    from_json = json_response.json()

    assert from_pdf["overall_status"] == from_json["overall_status"]
    assert from_pdf["passed_count"] == from_json["passed_count"]
    assert from_pdf["failed_count"] == from_json["failed_count"]
    assert from_pdf["unknown_count"] == from_json["unknown_count"]
    assert from_pdf["rule_coverage"] == from_json["rule_coverage"]
    assert from_pdf["patient"]["patient_id"] == from_json["patient"]["patient_id"]
    assert from_pdf["trial"]["trial_id"] == from_json["trial"]["trial_id"]

    statuses_pdf = {r["criterion_id"]: r["status"] for r in from_pdf["criteria_results"]}
    statuses_json = {r["criterion_id"]: r["status"] for r in from_json["criteria_results"]}
    assert statuses_pdf == statuses_json

    assert [d["criterion_id"] for d in from_pdf["disagreements"]] == [
        d["criterion_id"] for d in from_json["disagreements"]
    ]


def test_screen_pdf_evidence_cites_pdf_locations(client):
    """Every criterion the engine could evaluate must trace back to a PDF line.

    Asserting per-criterion rather than "at least one somewhere" — that weaker
    form hid a real gap where patient age carried no provenance.
    """
    response = client.post(
        "/screen/pdf",
        files={"file": ("demo_screening.pdf", _require_pdf("demo_screening.pdf"), "application/pdf")},
    )

    for row in response.json()["criteria_results"]:
        if row["status"] == "UNKNOWN":
            continue  # nothing was resolved, so there is no source line to cite
        locators = [e["locator"] or "" for e in row["evidence"]]
        assert any(
            loc.startswith("page ") for loc in locators
        ), f"{row['criterion_id']} has no PDF locator: {locators}"


def test_eligible_pdf_is_eligible(client):
    response = client.post(
        "/screen/pdf",
        files={"file": ("demo_eligible.pdf", _require_pdf("demo_eligible.pdf"), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["overall_status"] == "ELIGIBLE"


# -- Case 6: malformed input -----------------------------------------------


def test_non_pdf_upload_returns_structured_error(client):
    response = client.post(
        "/screen/pdf",
        files={"file": ("notes.txt", b"this is not a pdf", "text/plain")},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "NOT_A_PDF"
    assert error["message"]


def test_corrupt_pdf_returns_structured_error(client):
    response = client.post(
        "/screen/pdf",
        files={"file": ("broken.pdf", b"%PDF-1.4\n garbage bytes \n%%EOF", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"UNREADABLE_PDF", "NO_TEXT", "UNRECOGNISED_LAYOUT"}


def test_empty_upload_returns_structured_error(client):
    response = client.post("/screen/pdf", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EMPTY_FILE"


def test_wrong_layout_pdf_returns_structured_error(client):
    response = client.post(
        "/screen/pdf",
        files={"file": ("summary.pdf", _require_pdf("demo_malformed.pdf"), "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"UNRECOGNISED_LAYOUT", "INCOMPLETE_DOCUMENT"}


def test_invalid_canonical_payload_returns_structured_error(client):
    response = client.post("/screen", json={"patient": {"age": "not a number"}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# -- persistence ------------------------------------------------------------


def test_results_persist_and_survive_a_new_app_instance(tmp_path):
    """DoD #7/#8: the store is durable, not in-memory."""
    store = tmp_path / "store.json"

    first = TestClient(create_app(ScreeningService(repository=JsonRepository(store))))
    created = first.post(
        "/screen",
        json={
            "patient": load_patient("patient_eligible").model_dump(mode="json"),
            "trial": load_trial("trial_supported").model_dump(mode="json"),
        },
    ).json()
    result_id = created["result_id"]

    # A brand-new app and repository object, as after a server restart.
    second = TestClient(create_app(ScreeningService(repository=JsonRepository(store))))

    fetched = second.get(f"/results/{result_id}")
    assert fetched.status_code == 200
    assert fetched.json()["result_id"] == result_id

    listed = second.get("/results").json()
    assert result_id in {r["result_id"] for r in listed}


def test_unknown_result_id_returns_404(client):
    response = client.get("/results/SR-does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESULT_NOT_FOUND"
