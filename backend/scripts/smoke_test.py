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

    print()
    if failures:
        print(f"FAILED — {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
