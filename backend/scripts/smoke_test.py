"""End-to-end smoke test against a running server.

Run the backend, then:  python scripts/smoke_test.py [base_url]

Checks the full Phase 1 happy path plus the error and persistence paths, and
prints a pass/fail line for each. Use it to rehearse the demo — if this is
green, the demo works.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "fixtures" / "pdf"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(name)


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0)

    print("\nHEALTH")
    health = client.get("/health")
    check("GET /health returns ok", health.status_code == 200 and health.json()["status"] == "ok")
    check("AI provider is the offline mock", health.json().get("ai_provider") == "mock-slm-v1")

    print("\nCANONICAL SCREENING  (POST /screen)")
    patient = json.loads((ROOT / "fixtures" / "patient_pdf_demo.json").read_text())
    trial = json.loads((ROOT / "fixtures" / "trial_demo.json").read_text())
    canonical = client.post("/screen", json={"patient": patient, "trial": trial})
    check("returns 200", canonical.status_code == 200)
    canonical_body = canonical.json()
    check(
        "overall status is REVIEW_REQUIRED",
        canonical_body["overall_status"] == "REVIEW_REQUIRED",
        canonical_body["status_reason"],
    )

    print("\nPDF SCREENING  (POST /screen/pdf)")
    pdf_bytes = (PDF_DIR / "demo_screening.pdf").read_bytes()
    pdf = client.post(
        "/screen/pdf",
        files={"file": ("demo_screening.pdf", pdf_bytes, "application/pdf")},
    )
    check("returns 200", pdf.status_code == 200)
    pdf_body = pdf.json()
    check(
        "overall status matches the canonical run",
        pdf_body["overall_status"] == canonical_body["overall_status"],
        f"{pdf_body['overall_status']} vs {canonical_body['overall_status']}",
    )
    check(
        "per-criterion verdicts match the canonical run",
        {r["criterion_id"]: r["status"] for r in pdf_body["criteria_results"]}
        == {r["criterion_id"]: r["status"] for r in canonical_body["criteria_results"]},
    )
    check("has an UNKNOWN criterion", pdf_body["unknown_count"] >= 1)
    check("has a rule/AI disagreement", len(pdf_body["disagreements"]) >= 1)
    check(
        "evidence cites PDF locations",
        any(
            (e.get("locator") or "").startswith("page ")
            for r in pdf_body["criteria_results"]
            for e in r["evidence"]
        ),
    )
    check("rule coverage is reported honestly", 0 < pdf_body["rule_coverage"] < 1,
          f"{pdf_body['rule_coverage']:.0%}")

    print("\nELIGIBLE PATH")
    eligible = client.post(
        "/screen/pdf",
        files={
            "file": (
                "demo_eligible.pdf",
                (PDF_DIR / "demo_eligible.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    check("demo_eligible.pdf is ELIGIBLE", eligible.json().get("overall_status") == "ELIGIBLE")

    print("\nERROR HANDLING")
    for name, payload, expected in [
        ("non-PDF upload", b"just text", {"NOT_A_PDF"}),
        ("empty upload", b"", {"EMPTY_FILE"}),
        ("corrupt PDF", b"%PDF-1.4\ngarbage\n%%EOF", {"UNREADABLE_PDF", "NO_TEXT", "UNRECOGNISED_LAYOUT"}),
    ]:
        response = client.post(
            "/screen/pdf", files={"file": ("f.pdf", payload, "application/pdf")}
        )
        body = response.json()
        check(
            f"{name} returns a structured 422",
            response.status_code == 422 and body.get("error", {}).get("code") in expected,
            body.get("error", {}).get("code", "no error body"),
        )

    wrong_layout = client.post(
        "/screen/pdf",
        files={
            "file": (
                "summary.pdf",
                (PDF_DIR / "demo_malformed.pdf").read_bytes(),
                "application/pdf",
            )
        },
    )
    check(
        "wrong-layout PDF returns a structured 422",
        wrong_layout.status_code == 422,
        wrong_layout.json().get("error", {}).get("code", ""),
    )

    print("\nPERSISTENCE")
    result_id = pdf_body["result_id"]
    fetched = client.get(f"/results/{result_id}")
    check("saved result can be fetched by id", fetched.status_code == 200)
    listed = client.get("/results").json()
    check("saved result appears in the list", result_id in {r["result_id"] for r in listed},
          f"{len(listed)} stored")
    check("unknown id returns 404", client.get("/results/SR-nope").status_code == 404)

    # ------------------------------------------------------------------
    # Phase 2: treatment monitoring
    # ------------------------------------------------------------------

    print("\nPHASE 2 · PROTOCOL")
    protocol = client.get("/monitoring/protocol").json()
    check("protocol declares itself synthetic", protocol.get("synthetic") is True)
    check(
        "protocol warns it is not clinical guidance",
        "not clinical guidance" in protocol.get("warning", "").lower(),
    )

    print("\nPHASE 2 · ELIGIBILITY GATE")
    # canonical_body is the P-1042 REVIEW_REQUIRED screening from earlier.
    refused = client.post(
        "/monitoring/treatments",
        json={
            "screening_result_id": canonical_body["result_id"],
            "drug_name": "Compound X",
        },
    )
    check(
        "REVIEW_REQUIRED is refused without an override",
        refused.status_code == 422
        and refused.json().get("error", {}).get("code") == "OVERRIDE_REQUIRED",
        refused.json().get("error", {}).get("code", ""),
    )

    missing = client.post(
        "/monitoring/treatments",
        json={"screening_result_id": "SR-nope", "drug_name": "Compound X"},
    )
    check("unknown screening returns 404", missing.status_code == 404)

    print("\nPHASE 2 · DEMO COHORT")
    seed = client.post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-001", "seed": 7, "windows": 5},
    )
    check("seeding returns 200", seed.status_code == 200)
    seed_body = seed.json()
    check("seeded data is labelled synthetic", seed_body.get("synthetic") is True)
    check("six trajectories seeded", len(seed_body.get("patients", [])) == 6)

    overview = client.get("/monitoring/trials/CT-001/overview").json()
    check("overview counts six patients", overview.get("total_patients") == 6,
          f"{overview.get('total_patients')} patients")
    check("overview flags patients needing attention", bool(overview.get("requiring_attention")))

    print("\nPHASE 2 · RISK TRAJECTORIES")
    deteriorating = client.get("/monitoring/patients/P-2003/cycle").json()
    check(
        "deteriorating patient reaches RED",
        deteriorating.get("effective_risk", {}).get("level") == "RED",
        deteriorating.get("effective_risk", {}).get("level", ""),
    )
    check(
        "RED holds the next dose",
        deteriorating.get("next_dose", {}).get("decision") == "HOLD",
        deteriorating.get("next_dose", {}).get("decision", ""),
    )
    check(
        "escalation raises an urgent intervention",
        any(
            i["action"] == "URGENT_ESCALATION"
            for i in deteriorating.get("interventions", [])
        ),
    )
    check(
        "a clinician notification was generated",
        len(deteriorating.get("notifications", [])) >= 1,
    )
    check(
        "contributing factors explain the verdict",
        len(deteriorating.get("risk", {}).get("contributing_factors", [])) >= 1,
    )

    recovering = client.get("/monitoring/patients/P-2005/cycle").json()
    check(
        "recovering patient returns to GREEN",
        recovering.get("effective_risk", {}).get("level") == "GREEN",
        recovering.get("effective_risk", {}).get("level", ""),
    )
    check(
        "recovered patient may proceed",
        recovering.get("next_dose", {}).get("decision") == "PROCEED",
        recovering.get("next_dose", {}).get("decision", ""),
    )

    print("\nPHASE 2 · DATA-QUALITY GATE")
    failing_sensor = client.get("/monitoring/patients/P-2006/cycle").json()
    effective = failing_sensor.get("effective_risk", {})
    check(
        "failing sensor produces UNKNOWN, not GREEN",
        effective.get("level") == "UNKNOWN",
        effective.get("level", ""),
    )
    check("the gate records that it fired", effective.get("gated") is True)
    check(
        "the model's own verdict is retained",
        effective.get("provider_level") in {"GREEN", "AMBER", "RED"},
        f"model said {effective.get('provider_level')}",
    )
    check(
        "UNKNOWN requests repeat observations rather than reassuring",
        any(
            i["action"] == "REQUEST_REPEAT_OBSERVATION"
            for i in failing_sensor.get("interventions", [])
        ),
    )
    check(
        "UNKNOWN never proceeds to the next dose",
        failing_sensor.get("next_dose", {}).get("decision") != "PROCEED",
        failing_sensor.get("next_dose", {}).get("decision", ""),
    )

    print("\nPHASE 2 · TIMELINE")
    timeline = client.get("/monitoring/patients/P-2003/timeline").json()
    types = {e["event_type"] for e in timeline}
    for expected in (
        "TREATMENT_REGISTERED",
        "DOSE_ADMINISTERED",
        "OBSERVATIONS_INGESTED",
        "RISK_ASSESSED",
        "RISK_TRANSITION",
        "INTERVENTION_RAISED",
        "NEXT_DOSE_ASSESSED",
    ):
        check(f"timeline records {expected}", expected in types)
    check(
        "timeline is chronological",
        [e["occurred_at"] for e in timeline]
        == sorted(e["occurred_at"] for e in timeline),
    )

    print("\nPHASE 2 · INVALID DATA")
    bad = client.post(
        "/monitoring/observations",
        json={
            "observations": [
                {
                    "patient_id": "P-2003",
                    "trial_id": "CT-001",
                    "recorded_at": "2026-08-16T12:00:00+00:00",
                    "measurement_type": "HEART_RATE",
                    "value": 900,
                    "unit": "bpm",
                }
            ]
        },
    ).json()
    check(
        "an impossible reading is refused and reported",
        bad.get("accepted_count") == 0 and len(bad.get("rejected", [])) == 1,
        bad.get("rejected", [{}])[0].get("reason", "")[:60],
    )

    wrong_unit = client.post(
        "/monitoring/observations",
        json={
            "observations": [
                {
                    "patient_id": "P-2003",
                    "trial_id": "CT-001",
                    "recorded_at": "2026-08-16T12:00:00+00:00",
                    "measurement_type": "TEMPERATURE",
                    "value": 98.6,
                    "unit": "F",
                }
            ]
        },
    ).json()
    check(
        "a wrong unit is refused, never converted",
        wrong_unit.get("accepted_count") == 0,
        "no conversion applied",
    )

    print()
    if failures:
        print(f"FAILED — {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
