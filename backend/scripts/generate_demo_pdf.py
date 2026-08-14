"""Generate the structured clinical PDFs used for the Phase 1 demo and tests.

Run:  python scripts/generate_demo_pdf.py

Produces three documents in backend/fixtures/pdf/:

  demo_screening.pdf   The headline demo. Deliberately not a clean pass — it
                       carries a borderline eGFR, a duplicated HbA1c with two
                       different values, a criterion outside the Phase 1 rule
                       vocabulary, and a condition that makes the mock AI
                       disagree with the rule engine. It exercises PASS,
                       UNKNOWN, borderline, contradiction and disagreement in
                       one screen.

  demo_eligible.pdf    A clean pass, for showing the ELIGIBLE path.

  demo_malformed.pdf   A valid PDF with the wrong layout, for showing the
                       structured error state.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pdf"

HEADING = ("Helvetica", "B", 12)
BODY = ("Helvetica", "", 10.5)


def _render(lines: list[str], path: Path) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    for line in lines:
        if line == "":
            pdf.ln(3)
            continue
        is_heading = line.isupper() and not line.startswith("-")
        pdf.set_font(*(HEADING if is_heading else BODY))
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))


def _trial_block() -> list[str]:
    return [
        "",
        "CLINICAL TRIAL",
        "Trial ID: CT-001",
        "Title: Phase III Glycaemic Control Study in Type 2 Diabetes",
        "",
        "INCLUSION",
        "- Age between 18 and 65 years",
        "- Diagnosis: Type 2 Diabetes",
        "- HbA1c between 7 and 10 %",
        "- eGFR at least 45 mL/min",
        "- Medication: Metformin",
        "",
        "EXCLUSION",
        "- Diagnosis: Severe cardiovascular disease",
        "- Prior exposure to investigational GLP-1 agonist within 6 months of screening",
    ]


def demo_screening() -> list[str]:
    return [
        "CLINICAL TRIAL SCREENING RECORD",
        "",
        "PATIENT INFORMATION",
        "Patient ID: P-1042",
        "Age: 54",
        "Sex: Male",
        "",
        "CONDITIONS",
        "- Type 2 Diabetes",
        "- Hypertension",
        "- Stable Angina",
        "",
        "LAB RESULTS",
        # Mixed date formats and a repeated analyte, on purpose.
        "HbA1c: 7.1 % (12/09/2025)",
        "HbA1c: 8.2 % (2026-03-11)",
        "eGFR: 47 mL/min (2026-03-11)",
        "",
        "MEDICATIONS",
        "- Metformin",
        "Duration: 5 months",
        *_trial_block(),
    ]


def demo_eligible() -> list[str]:
    return [
        "CLINICAL TRIAL SCREENING RECORD",
        "",
        "PATIENT INFORMATION",
        "Patient ID: P-1001",
        "Age: 54",
        "Sex: Male",
        "",
        "CONDITIONS",
        "- Type 2 Diabetes",
        "- Hypertension",
        "",
        "LAB RESULTS",
        "HbA1c: 8.2 % (2026-03-11)",
        "eGFR: 62 mL/min (2026-03-11)",
        "",
        "MEDICATIONS",
        "- Metformin",
        "Duration: 5 months",
        "",
        "CLINICAL TRIAL",
        "Trial ID: CT-002",
        "Title: Glycaemic Control Study",
        "",
        "INCLUSION",
        "- Age between 18 and 65 years",
        "- Diagnosis: Type 2 Diabetes",
        "- HbA1c between 7 and 10 %",
        "- eGFR at least 45 mL/min",
        "- Medication: Metformin",
        "",
        "EXCLUSION",
        "- Diagnosis: Severe cardiovascular disease",
    ]


def demo_malformed() -> list[str]:
    return [
        "DISCHARGE SUMMARY",
        "",
        "The patient was seen in clinic and is doing well.",
        "Follow up in three months.",
    ]


def main() -> int:
    for name, builder in (
        ("demo_screening", demo_screening),
        ("demo_eligible", demo_eligible),
        ("demo_malformed", demo_malformed),
    ):
        path = OUTPUT_DIR / f"{name}.pdf"
        _render(builder(), path)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
