"""M10: the Phase 2 HTTP surface.

Also guards the boundary that matters most for this milestone: mounting the
monitoring router must not disturb any Phase 1 route.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.fixtures_loader import load_patient, load_trial
from app.main import create_app
from app.monitoring.context import MonitoringContext
from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.json_repo import JsonRepository
from app.service import ScreeningService

START = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path):
    screening_repo = JsonRepository(tmp_path / "store.json")
    service = ScreeningService(repository=screening_repo)
    monitoring = MonitoringContext.build(
        screening_repo, JsonMonitoringRepository(tmp_path / "monitoring.json")
    )
    return TestClient(create_app(service, monitoring))


def _screen(client, patient="patient_eligible", trial="trial_supported") -> dict:
    response = client.post(
        "/screen",
        json={
            "patient": load_patient(patient).model_dump(mode="json"),
            "trial": load_trial(trial).model_dump(mode="json"),
        },
    )
    assert response.status_code == 200
    return response.json()


def _register(client, screening, **extra) -> dict:
    payload = {
        "screening_result_id": screening["result_id"],
        "drug_name": "Compound X",
        "now": START.isoformat(),
        **extra,
    }
    return client.post("/monitoring/treatments", json=payload)


def _observations(patient_id, trial_id, at, hr=72.0, spo2=98.0, sbp=120.0):
    return [
        {
            "patient_id": patient_id,
            "trial_id": trial_id,
            "recorded_at": at.isoformat(),
            "measurement_type": measurement,
            "value": value,
            "unit": unit,
            "source": "SYNTHETIC",
        }
        for measurement, value, unit in (
            ("HEART_RATE", hr, "bpm"),
            ("SPO2", spo2, "%"),
            ("SYSTOLIC_BP", sbp, "mmHg"),
        )
    ]


# -- Phase 1 preservation --------------------------------------------------


def test_phase_one_routes_still_work(client):
    assert client.get("/health").json()["status"] == "ok"

    screening = _screen(client)
    assert screening["overall_status"] == "ELIGIBLE"

    assert client.get("/results").status_code == 200
    assert client.get(f"/results/{screening['result_id']}").status_code == 200
    assert client.get("/results/SR-nope").status_code == 404


def test_phase_one_error_envelope_is_unchanged(client):
    response = client.post("/screen", json={"patient": {"age": "not a number"}})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# -- protocol transparency -------------------------------------------------


def test_protocol_endpoint_declares_itself_synthetic(client):
    body = client.get("/monitoring/protocol").json()

    assert body["synthetic"] is True
    assert "not clinical guidance" in body["warning"].lower()
    assert body["protocol_id"] == "DEMO-PROTOCOL-1"
    assert "HEART_RATE" in body["normal_band"]


# -- treatments ------------------------------------------------------------


def test_register_treatment_from_an_eligible_screening(client):
    response = _register(client, _screen(client))

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == "P-1001"
    assert body["status"] == "ACTIVE"
    assert body["override"] is None


def test_review_required_without_override_is_rejected(client):
    screening = _screen(client, "patient_pdf_demo", "trial_demo")

    response = _register(client, screening)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OVERRIDE_REQUIRED"


def test_review_required_with_override_is_accepted(client):
    screening = _screen(client, "patient_pdf_demo", "trial_demo")

    response = _register(
        client, screening, override_by="Dr. Chen", override_reason="Reviewed."
    )

    assert response.status_code == 200
    assert response.json()["override"]["approved_by"] == "Dr. Chen"


def test_ineligible_screening_is_refused(client):
    screening = _screen(client, "patient_ineligible", "trial_supported")

    response = _register(client, screening)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TREATMENT_NOT_PERMITTED"


def test_unknown_screening_returns_404(client):
    response = client.post(
        "/monitoring/treatments",
        json={"screening_result_id": "SR-nope", "drug_name": "X"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCREENING_NOT_FOUND"


def test_duplicate_active_treatment_returns_409(client):
    screening = _screen(client)
    _register(client, screening)

    response = _register(client, screening)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TREATMENT_ALREADY_ACTIVE"


def test_record_a_dose(client):
    treatment = _register(client, _screen(client)).json()

    response = client.post(
        f"/monitoring/treatments/{treatment['treatment_id']}/doses",
        json={"amount": 5, "unit": "mg", "now": START.isoformat()},
    )

    assert response.status_code == 200
    assert len(response.json()["doses"]) == 1


def test_dose_on_unknown_treatment_returns_404(client):
    response = client.post(
        "/monitoring/treatments/TX-nope/doses", json={"amount": 5, "unit": "mg"}
    )

    assert response.status_code == 404


def test_list_treatments_filters(client):
    treatment = _register(client, _screen(client)).json()

    listed = client.get(
        "/monitoring/treatments", params={"trial_id": treatment["trial_id"]}
    ).json()

    assert [t["treatment_id"] for t in listed] == [treatment["treatment_id"]]


# -- observations ----------------------------------------------------------


def test_ingest_observations(client):
    treatment = _register(client, _screen(client)).json()

    response = client.post(
        "/monitoring/observations",
        json={
            "observations": _observations(
                treatment["patient_id"], treatment["trial_id"], START
            ),
            "now": START.isoformat(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_count"] == 3
    assert body["rejected"] == []


def test_invalid_observations_are_reported_not_dropped(client):
    treatment = _register(client, _screen(client)).json()
    rows = _observations(treatment["patient_id"], treatment["trial_id"], START)
    rows[0]["value"] = 900.0  # impossible heart rate

    body = client.post(
        "/monitoring/observations", json={"observations": rows, "now": START.isoformat()}
    ).json()

    assert body["accepted_count"] == 2
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["reason"]


def test_empty_observation_batch_is_rejected_by_validation(client):
    response = client.post("/monitoring/observations", json={"observations": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_measurement_type_is_rejected(client):
    rows = _observations("P-1001", "CT-002", START)
    rows[0]["measurement_type"] = "BLOOD_GLUCOSE"

    response = client.post("/monitoring/observations", json={"observations": rows})

    assert response.status_code == 422


# -- cycle, state, timeline ------------------------------------------------


def _prepare(client):
    """Register, ingest and run one cycle. Returns the treatment."""
    treatment = _register(client, _screen(client)).json()
    for step in range(4):
        at = START + timedelta(minutes=step * 10)
        client.post(
            "/monitoring/observations",
            json={
                "observations": _observations(
                    treatment["patient_id"], treatment["trial_id"], at
                ),
                "now": at.isoformat(),
            },
        )
    return treatment


def test_run_cycle_returns_the_whole_decision_record(client):
    treatment = _prepare(client)
    at = START + timedelta(minutes=30)

    response = client.post(
        f"/monitoring/patients/{treatment['patient_id']}/cycle",
        json={"trial_id": treatment["trial_id"], "now": at.isoformat()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["risk"]["provider"] == "mock-risk-v1"
    assert body["effective_risk"]["level"] == "GREEN"
    assert body["interventions"]
    assert body["next_dose"]["decision"] == "PROCEED"
    assert body["next_dose"]["decision_support_only"] is True
    assert body["state"]["measurements"]


def test_latest_cycle_is_404_before_any_run(client):
    response = client.get("/monitoring/patients/P-nobody/cycle")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_CYCLE"


def test_patient_state_is_computed_on_read(client):
    treatment = _prepare(client)

    response = client.get(
        f"/monitoring/patients/{treatment['patient_id']}/state",
        params={"trial_id": treatment["trial_id"], "now": (START + timedelta(minutes=30)).isoformat()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["observation_count"] == 12
    assert body["measurements"]
    # State carries no risk — risk is computed from it.
    assert "risk" not in body


def test_timeline_returns_events_in_order(client):
    treatment = _prepare(client)
    at = START + timedelta(minutes=30)
    client.post(
        f"/monitoring/patients/{treatment['patient_id']}/cycle",
        json={"trial_id": treatment["trial_id"], "now": at.isoformat()},
    )

    events = client.get(
        f"/monitoring/patients/{treatment['patient_id']}/timeline"
    ).json()

    types = [e["event_type"] for e in events]
    assert "TREATMENT_REGISTERED" in types
    assert "OBSERVATIONS_INGESTED" in types
    assert "RISK_ASSESSED" in types
    assert [e["occurred_at"] for e in events] == sorted(e["occurred_at"] for e in events)


# -- dashboard and seeding -------------------------------------------------


def test_trial_overview_is_empty_before_seeding(client):
    body = client.get("/monitoring/trials/CT-001/overview").json()

    assert body["total_patients"] == 0
    assert body["risk_counts"]["GREEN"] == 0


def test_demo_seed_populates_the_full_cohort(client):
    response = client.post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-001", "seed": 7, "windows": 5, "start": START.isoformat()},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["synthetic"] is True
    assert len(body["patients"]) == 6

    progressions = {p["patient_id"]: p["risk_progression"] for p in body["patients"]}
    # The deteriorating patient escalates; the recovering one settles.
    assert progressions["P-2003"][-1] == "RED"
    assert progressions["P-2005"][-1] == "GREEN"
    # The failing sensor lands on UNKNOWN, not a reassuring GREEN.
    assert progressions["P-2006"][-1] == "UNKNOWN"


def test_overview_after_seeding_shows_the_spread(client):
    client.post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-001", "seed": 7, "windows": 5, "start": START.isoformat()},
    )

    body = client.get("/monitoring/trials/CT-001/overview").json()

    assert body["total_patients"] == 6
    assert body["active_treatments"] == 6
    assert body["risk_counts"]["RED"] >= 1
    assert body["risk_counts"]["UNKNOWN"] >= 1
    assert body["requiring_attention"]
    # RED sorts ahead of AMBER in the attention list.
    assert body["requiring_attention"][0]["risk_level"] == "RED"


def test_seeding_twice_does_not_duplicate_treatments(client):
    payload = {"trial_id": "CT-001", "seed": 7, "windows": 2, "start": START.isoformat()}
    client.post("/monitoring/demo/seed", json=payload)
    second = client.post("/monitoring/demo/seed", json=payload).json()

    assert all("skipped" in p for p in second["patients"])
    assert client.get("/monitoring/trials/CT-001/overview").json()["total_patients"] == 6
