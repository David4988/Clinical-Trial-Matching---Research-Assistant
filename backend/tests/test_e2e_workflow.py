"""The judge-facing lifecycle, end to end over the HTTP surface.

    screening -> REVIEW_REQUIRED -> human review -> approve
      -> Phase 2 participant -> administration -> monitoring
      -> risk signal -> investigator review

One participant, one continuous chain of ids. The fixtures used here are the
same ones the demo record uses (`patient_pdf_demo` against `trial_demo`), which
is what makes this file a regression test for the demo itself and not just for
the endpoints in isolation.

What these tests are guarding, beyond "the route returns 200":

  * a review is recorded *beside* the deterministic verdict and cannot alter it
  * a reviewer's approval is what carries a REVIEW_REQUIRED patient into Phase 2
  * a reviewer who asked for more review blocks enrolment, and cannot be
    routed around by supplying an override in the same request
  * an investigator decision never changes a risk level or an intervention
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.fixtures_loader import load_patient, load_trial
from app.main import create_app
from app.monitoring.context import MonitoringContext
from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.json_repo import JsonRepository
from app.risk.factory import build_risk_provider
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


def _screen(client, patient: str, trial: str) -> dict:
    response = client.post(
        "/screen",
        json={
            "patient": load_patient(patient).model_dump(mode="json"),
            "trial": load_trial(trial).model_dump(mode="json"),
        },
    )
    assert response.status_code == 200
    return response.json()


def _review_required(client) -> dict:
    """The demo record: the screening a judge actually sees on screen."""
    result = _screen(client, "patient_pdf_demo", "trial_demo")
    assert result["overall_status"] == "REVIEW_REQUIRED"
    return result


def _approve(client, screening, reviewer="Dr. A. Reyes", note="Conflict reviewed."):
    return client.post(
        f"/results/{screening['result_id']}/review",
        json={
            "decision": "APPROVED_FOR_PHASE_2",
            "reviewer": reviewer,
            "note": note,
            "now": START.isoformat(),
        },
    )


def _register(client, screening, **extra):
    return client.post(
        "/monitoring/treatments",
        json={
            "screening_result_id": screening["result_id"],
            "drug_name": "Compound X",
            "now": START.isoformat(),
            **extra,
        },
    )


# -- human review ----------------------------------------------------------


def test_review_is_recorded_on_the_screening(client):
    screening = _review_required(client)
    response = _approve(client, screening)

    assert response.status_code == 200
    review = response.json()["review"]
    assert review["decision"] == "APPROVED_FOR_PHASE_2"
    assert review["reviewer"] == "Dr. A. Reyes"
    assert review["note"] == "Conflict reviewed."
    # The verdict that was actually in front of the reviewer.
    assert review["reviewed_status"] == "REVIEW_REQUIRED"


def test_review_leaves_every_deterministic_field_untouched(client):
    screening = _review_required(client)
    reviewed = _approve(client, screening).json()

    for field in (
        "overall_status",
        "criteria_results",
        "passed_count",
        "failed_count",
        "unknown_count",
        "rule_coverage",
        "heuristic_flags",
        "disagreements",
        "status_reason",
    ):
        assert reviewed[field] == screening[field], f"{field} was mutated by a review"


def test_review_survives_a_reload(client):
    screening = _review_required(client)
    _approve(client, screening)

    stored = client.get(f"/results/{screening['result_id']}").json()
    assert stored["review"]["reviewer"] == "Dr. A. Reyes"


def test_a_screening_starts_with_no_review(client):
    assert _review_required(client)["review"] is None


@pytest.mark.parametrize("field", ["reviewer", "note"])
def test_review_requires_a_name_and_a_reason(client, field):
    screening = _review_required(client)
    payload = {
        "decision": "APPROVED_FOR_PHASE_2",
        "reviewer": "Dr. A. Reyes",
        "note": "Conflict reviewed.",
    }
    payload[field] = "   "

    response = client.post(f"/results/{screening['result_id']}/review", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {
        "REVIEWER_REQUIRED",
        "REVIEW_NOTE_REQUIRED",
    }


def test_an_ineligible_screening_cannot_be_approved(client):
    screening = _screen(client, "patient_ineligible", "trial_supported")
    assert screening["overall_status"] == "INELIGIBLE"

    response = _approve(client, screening)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "APPROVAL_NOT_PERMITTED"


def test_reviewing_an_unknown_result_is_a_404(client):
    response = client.post(
        "/results/SR-does-not-exist/review",
        json={
            "decision": "APPROVED_FOR_PHASE_2",
            "reviewer": "Dr. A. Reyes",
            "note": "n/a",
        },
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESULT_NOT_FOUND"


# -- Phase 1 -> Phase 2 ----------------------------------------------------


def test_approval_carries_the_patient_into_phase_two(client):
    screening = _review_required(client)
    _approve(client, screening)

    response = _register(client, screening)
    assert response.status_code == 200
    treatment = response.json()

    # The same logical participant, not a new one.
    assert treatment["patient_id"] == screening["patient"]["patient_id"]
    assert treatment["screening_result_id"] == screening["result_id"]

    # The override is the reviewer's decision, not a second unrelated approval.
    assert treatment["override"]["approved_by"] == "Dr. A. Reyes"
    assert treatment["override"]["reason"] == "Conflict reviewed."
    assert treatment["override"]["screening_status"] == "REVIEW_REQUIRED"


def test_registration_without_a_review_still_demands_an_override(client):
    """The pre-existing contract: unchanged for callers that never review."""
    screening = _review_required(client)

    response = _register(client, screening)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OVERRIDE_REQUIRED"


def test_requesting_further_review_blocks_enrolment(client):
    screening = _review_required(client)
    client.post(
        f"/results/{screening['result_id']}/review",
        json={
            "decision": "FURTHER_REVIEW_REQUESTED",
            "reviewer": "Dr. A. Reyes",
            "note": "Needs a repeat panel.",
            "now": START.isoformat(),
        },
    )

    response = _register(client, screening)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVIEW_PENDING"


def test_a_pending_review_cannot_be_overridden_by_the_caller(client):
    """An explicit override must not route around a reviewer's "not yet"."""
    screening = _review_required(client)
    client.post(
        f"/results/{screening['result_id']}/review",
        json={
            "decision": "FURTHER_REVIEW_REQUESTED",
            "reviewer": "Dr. A. Reyes",
            "note": "Needs a repeat panel.",
        },
    )

    response = _register(
        client,
        screening,
        override_by="Someone Else",
        override_reason="Proceeding anyway.",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVIEW_PENDING"


def test_the_transition_is_on_the_timeline(client):
    screening = _review_required(client)
    _approve(client, screening)
    _register(client, screening)

    patient_id = screening["patient"]["patient_id"]
    events = client.get(f"/monitoring/patients/{patient_id}/timeline").json()
    kinds = [event["event_type"] for event in events]

    assert "TREATMENT_REGISTERED" in kinds
    assert "ELIGIBILITY_OVERRIDE_RECORDED" in kinds


# -- administration --------------------------------------------------------


@pytest.fixture
def participant(client):
    """A reviewed, approved, enrolled participant — the demo's starting point."""
    screening = _review_required(client)
    _approve(client, screening)
    treatment = _register(client, screening).json()
    return {
        "screening": screening,
        "treatment": treatment,
        "patient_id": treatment["patient_id"],
        "trial_id": treatment["trial_id"],
    }


def test_a_dose_records_amount_route_and_administrator(client, participant):
    response = client.post(
        f"/monitoring/treatments/{participant['treatment']['treatment_id']}/doses",
        json={
            "amount": 5.0,
            "unit": "mg",
            "route": "IV",
            "administered_by": "Nurse J. Okafor",
            "now": START.isoformat(),
        },
    )
    assert response.status_code == 200

    dose = response.json()["doses"][-1]
    assert dose["dose_number"] == 1
    assert dose["amount"] == 5.0
    assert dose["unit"] == "mg"
    assert dose["route"] == "IV"
    assert dose["administered_by"] == "Nurse J. Okafor"


def test_a_dose_without_a_route_is_still_accepted(client, participant):
    """`route` is additive: existing callers that never send it keep working."""
    response = client.post(
        f"/monitoring/treatments/{participant['treatment']['treatment_id']}/doses",
        json={"amount": 5.0, "unit": "mg", "now": START.isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["doses"][-1]["route"] is None


def test_administration_reaches_the_timeline(client, participant):
    client.post(
        f"/monitoring/treatments/{participant['treatment']['treatment_id']}/doses",
        json={"amount": 5.0, "unit": "mg", "route": "IV", "now": START.isoformat()},
    )

    events = client.get(
        f"/monitoring/patients/{participant['patient_id']}/timeline"
    ).json()
    dosed = [e for e in events if e["event_type"] == "DOSE_ADMINISTERED"]
    assert len(dosed) == 1
    assert dosed[0]["payload"]["route"] == "IV"


# -- monitoring ------------------------------------------------------------


def _advance(client, participant, window_index: int, **extra):
    return client.post(
        f"/monitoring/patients/{participant['patient_id']}/advance",
        json={
            "trial_id": participant["trial_id"],
            "window_index": window_index,
            "windows": 5,
            "seed": 42,
            "start": START.isoformat(),
            **extra,
        },
    )


def test_advancing_produces_a_monitoring_cycle(client, participant):
    response = _advance(client, participant, 0)
    assert response.status_code == 200

    cycle = response.json()
    assert cycle["patient_id"] == participant["patient_id"]
    assert cycle["state"]["observation_count"] > 0
    # The advisory/authoritative split still holds on this path.
    assert cycle["risk"]["provider"]
    assert "level" in cycle["effective_risk"]


def test_advancing_replays_identically_from_a_clean_store(client, participant, tmp_path):
    """Same seed, same window, same observations — the demo is reproducible."""
    first = [
        (o["measurement_type"], o["value"])
        for o in _advance(client, participant, 0).json()["state"]["recent_observations"]
    ]
    assert first

    # A second, independent application over its own stores, same inputs.
    screening_repo = JsonRepository(tmp_path / "replay-store.json")
    service = ScreeningService(repository=screening_repo)
    monitoring = MonitoringContext.build(
        screening_repo, JsonMonitoringRepository(tmp_path / "replay-monitoring.json")
    )
    replay = TestClient(create_app(service, monitoring))

    screening = _review_required(replay)
    _approve(replay, screening)
    treatment = _register(replay, screening).json()
    second = [
        (o["measurement_type"], o["value"])
        for o in _advance(
            replay,
            {"patient_id": treatment["patient_id"], "trial_id": treatment["trial_id"]},
            0,
        ).json()["state"]["recent_observations"]
    ]

    assert second == first


def test_advancing_walks_the_risk_trajectory(client, participant):
    levels = [
        _advance(client, participant, index).json()["effective_risk"]["level"]
        for index in range(5)
    ]

    # Provider-agnostic on purpose: which levels appear is the risk provider's
    # business, and this suite runs against the default. What the *pipeline*
    # must guarantee is that a deterioration trajectory actually deteriorates,
    # and that it does not open at RED on the first window.
    assert "RED" in levels
    assert levels.index("RED") > 0
    assert levels[-1] == "RED"


def test_advancing_requires_an_enrolled_participant(client):
    response = client.post(
        "/monitoring/patients/P-NOT-ENROLLED/advance",
        json={"trial_id": "CT-001", "window_index": 0},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TREATMENT_NOT_FOUND"


def test_a_window_beyond_the_generated_set_is_refused(client, participant):
    response = _advance(client, participant, 9)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "WINDOW_OUT_OF_RANGE"


def test_the_live_ml_provider_drives_the_demo_trajectory(tmp_path):
    """The judge-facing path with RISK_PROVIDER=synthetic_ml.

    Guards the claim the UI makes when it says inference is LIVE: the levels
    shown during the demo come from the serialized Isolation Forest scoring the
    generated windows, not from the deterministic mock. Skipped rather than
    failed where the ML extras are not installed, so the default suite stays
    dependency-free.
    """
    ml = pytest.importorskip("joblib") and build_risk_provider("synthetic_ml")

    screening_repo = JsonRepository(tmp_path / "ml-store.json")
    service = ScreeningService(repository=screening_repo)
    monitoring = MonitoringContext.build(
        screening_repo,
        JsonMonitoringRepository(tmp_path / "ml-monitoring.json"),
        risk_provider=ml,
    )
    client = TestClient(create_app(service, monitoring))

    screening = _review_required(client)
    _approve(client, screening)
    treatment = _register(client, screening).json()
    participant = {
        "patient_id": treatment["patient_id"],
        "trial_id": treatment["trial_id"],
    }

    cycles = [_advance(client, participant, index).json() for index in range(5)]
    levels = [c["effective_risk"]["level"] for c in cycles]

    # Real inference, and the provenance says so.
    assert {c["risk"]["provider"] for c in cycles} == {"synthetic_ml"}
    # A real model produces a spread of scores, not one constant.
    assert len({round(c["risk"]["score"], 3) for c in cycles}) > 1

    # The transition the demo depends on, and the protocol response to it.
    assert levels[0] in {"GREEN", "UNKNOWN"}
    assert levels[-1] == "RED"

    actions = {
        i["action"] for i in cycles[-1]["interventions"]
    }
    assert "URGENT_ESCALATION" in actions

    model = client.get("/monitoring/model").json()
    assert model["provider"] == "synthetic_ml"
    assert model["live_inference"] is True


# -- investigator review ---------------------------------------------------


@pytest.fixture
def monitored(client, participant):
    """A participant with a monitoring cycle on record."""
    client.post(
        f"/monitoring/treatments/{participant['treatment']['treatment_id']}/doses",
        json={"amount": 5.0, "unit": "mg", "route": "IV", "now": START.isoformat()},
    )
    for index in range(5):
        _advance(client, participant, index)
    return participant


def _review(client, monitored, action, reviewer="Dr. S. Mbeki", note="Reviewed."):
    return client.post(
        f"/monitoring/patients/{monitored['patient_id']}/investigator-review",
        json={"action": action, "reviewer": reviewer, "note": note},
    )


def test_acknowledging_records_the_decision(client, monitored):
    response = _review(client, monitored, "ACKNOWLEDGE", note="Seen, vitals trending.")
    assert response.status_code == 200

    review = response.json()
    assert review["action"] == "ACKNOWLEDGE"
    assert review["reviewer"] == "Dr. S. Mbeki"
    assert review["risk_level"] in {"GREEN", "AMBER", "RED", "UNKNOWN"}
    # An acknowledgement claims nothing about the treatment.
    assert review["treatment_status_after"] is None


def test_an_investigator_review_does_not_change_the_cycle(client, monitored):
    before = client.get(f"/monitoring/patients/{monitored['patient_id']}/cycle").json()
    _review(client, monitored, "ACKNOWLEDGE")
    after = client.get(f"/monitoring/patients/{monitored['patient_id']}/cycle").json()

    assert after["effective_risk"] == before["effective_risk"]
    assert after["risk"] == before["risk"]
    assert after["interventions"] == before["interventions"]


def test_holding_places_the_treatment_on_hold(client, monitored):
    review = _review(
        client, monitored, "HOLD_TREATMENT", note="Holding pending review."
    ).json()
    assert review["treatment_status_after"] == "ON_HOLD"

    treatment = client.get(
        f"/monitoring/treatments/{monitored['treatment']['treatment_id']}"
    ).json()
    assert treatment["status"] == "ON_HOLD"


def test_continuing_monitoring_leaves_the_treatment_active(client, monitored):
    _review(client, monitored, "CONTINUE_MONITORING", note="Continue, recheck at 4h.")

    treatment = client.get(
        f"/monitoring/treatments/{monitored['treatment']['treatment_id']}"
    ).json()
    assert treatment["status"] == "ACTIVE"


def test_a_review_reaches_the_timeline_and_the_review_list(client, monitored):
    _review(client, monitored, "ACKNOWLEDGE", note="Seen.")

    events = client.get(
        f"/monitoring/patients/{monitored['patient_id']}/timeline"
    ).json()
    assert any(e["event_type"] == "INVESTIGATOR_REVIEW_RECORDED" for e in events)

    reviews = client.get(
        f"/monitoring/patients/{monitored['patient_id']}/investigator-reviews"
    ).json()
    assert len(reviews) == 1
    assert reviews[0]["note"] == "Seen."


@pytest.mark.parametrize("field", ["reviewer", "note"])
def test_an_investigator_review_requires_a_name_and_a_reason(client, monitored, field):
    payload = {"action": "ACKNOWLEDGE", "reviewer": "Dr. S. Mbeki", "note": "Seen."}
    payload[field] = "  "

    response = client.post(
        f"/monitoring/patients/{monitored['patient_id']}/investigator-review",
        json=payload,
    )
    assert response.status_code == 422


def test_reviewing_a_patient_with_no_cycle_is_refused(client, participant):
    response = _review(client, participant, "ACKNOWLEDGE")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_CYCLE"


# -- the whole chain -------------------------------------------------------


def test_one_participant_through_the_entire_lifecycle(client):
    """The demo, as a test. Every step keyed to the same participant."""
    screening = _review_required(client)
    patient_id = screening["patient"]["patient_id"]

    reviewed = _approve(client, screening, note="Rule/AI conflict reviewed.").json()
    assert reviewed["review"]["decision"] == "APPROVED_FOR_PHASE_2"
    assert reviewed["overall_status"] == "REVIEW_REQUIRED"  # still immutable

    treatment = _register(client, screening).json()
    assert treatment["patient_id"] == patient_id

    dosed = client.post(
        f"/monitoring/treatments/{treatment['treatment_id']}/doses",
        json={"amount": 5.0, "unit": "mg", "route": "IV", "now": START.isoformat()},
    ).json()
    assert dosed["doses"][-1]["dose_number"] == 1

    participant = {"patient_id": patient_id, "trial_id": treatment["trial_id"]}
    levels = [
        _advance(client, participant, index).json()["effective_risk"]["level"]
        for index in range(5)
    ]
    assert "RED" in levels

    review = _review(
        client,
        participant,
        "HOLD_TREATMENT",
        note="RED signal reviewed; holding.",
    ).json()
    assert review["risk_level"] == levels[-1]
    assert review["treatment_status_after"] == "ON_HOLD"

    # One continuous audit trail for one participant.
    events = client.get(f"/monitoring/patients/{patient_id}/timeline").json()
    kinds = [e["event_type"] for e in events]
    for expected in (
        "TREATMENT_REGISTERED",
        "ELIGIBILITY_OVERRIDE_RECORDED",
        "DOSE_ADMINISTERED",
        "RISK_ASSESSED",
        "INTERVENTION_RAISED",
        "INVESTIGATOR_REVIEW_RECORDED",
    ):
        assert expected in kinds, f"{expected} missing from the timeline"
