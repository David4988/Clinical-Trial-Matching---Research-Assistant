"""Structured clinical document -> canonical Patient + Trial.

A section-driven state machine over `TextLine`s. Deterministic by design: no
model, no inference, no fuzzy matching. Every value it produces carries an
Evidence locator pointing back at the line it came from.

Phase 1 deliberately parses a document layout we control. The parser's job is
to be *correct and traceable*, not general — generality is what the Phase 2
LLM extractor is for, and it will emit these same canonical types.
"""

from __future__ import annotations

import re

from .criterion_parser import parse_criterion_text
from .errors import ExtractionError
from .pdf_reader import TextLine, read_lines
from ..schema.clinical import Condition, Evidence, LabResult, Medication, Patient
from ..schema.enums import ClinicalStatus, CriterionKind, EvidenceSource, Sex
from ..schema.trial import Criterion, Trial

SECTION_HEADINGS = {
    "PATIENT INFORMATION": "patient",
    "CONDITIONS": "conditions",
    "LAB RESULTS": "labs",
    "MEDICATIONS": "medications",
    "CLINICAL TRIAL": "trial",
    "INCLUSION": "inclusion",
    "INCLUSION CRITERIA": "inclusion",
    "EXCLUSION": "exclusion",
    "EXCLUSION CRITERIA": "exclusion",
}

_BULLET = re.compile(r"^[-•*]\s*(.+)$")
_KEY_VALUE = re.compile(r"^([A-Za-z][A-Za-z0-9 /()_-]*?)\s*:\s*(.+)$")
_LAB = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9 \-/]*?)\s*:\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>[^\s(][^\s]*)?"
    r"(?:\s*\((?P<date>[^)]+)\))?\s*$"
)

_SEX_MAP = {
    "male": Sex.MALE,
    "m": Sex.MALE,
    "female": Sex.FEMALE,
    "f": Sex.FEMALE,
    "other": Sex.OTHER,
}


def parse_document(data: bytes) -> tuple[Patient, Trial]:
    """Parse PDF bytes into canonical models, or raise ExtractionError."""
    return parse_lines(read_lines(data))


def parse_lines(lines: list[TextLine]) -> tuple[Patient, Trial]:
    sections = _split_sections(lines)

    patient = _build_patient(sections)
    trial = _build_trial(sections)

    problems: list[str] = []
    if not patient.patient_id:
        problems.append("Patient ID is missing from the PATIENT INFORMATION section.")
    if not trial.trial_id:
        problems.append("Trial ID is missing from the CLINICAL TRIAL section.")
    if not trial.criteria:
        problems.append("No INCLUSION or EXCLUSION criteria were found.")
    if problems:
        raise ExtractionError(
            "INCOMPLETE_DOCUMENT",
            "The document is missing information required to screen a patient.",
            problems,
        )
    return patient, trial


# -- sectioning -----------------------------------------------------------


def _split_sections(lines: list[TextLine]) -> dict[str, list[TextLine]]:
    sections: dict[str, list[TextLine]] = {name: [] for name in set(SECTION_HEADINGS.values())}
    current: str | None = None

    for line in lines:
        heading = SECTION_HEADINGS.get(line.text.strip().upper())
        if heading is not None:
            current = heading
            continue
        if current is not None:
            sections[current].append(line)

    if not any(sections.values()):
        raise ExtractionError(
            "UNRECOGNISED_LAYOUT",
            "The document does not match the expected structured clinical layout.",
            [f"Expected one of these headings: {', '.join(sorted(SECTION_HEADINGS))}."],
        )
    return sections


def _evidence(line: TextLine, note: str | None = None) -> Evidence:
    return Evidence(
        source_type=EvidenceSource.PDF_FIELD,
        locator=line.locator,
        snippet=line.text,
        note=note,
    )


# -- patient --------------------------------------------------------------


def _build_patient(sections: dict[str, list[TextLine]]) -> Patient:
    patient_id = ""
    age: int | None = None
    age_source: Evidence | None = None
    sex = Sex.UNKNOWN

    for line in sections["patient"]:
        match = _KEY_VALUE.match(line.text)
        if not match:
            continue
        key, value = match.group(1).strip().lower(), match.group(2).strip()
        if key in {"patient id", "patient identifier", "id"}:
            patient_id = value
        elif key == "age":
            digits = re.search(r"\d+", value)
            if digits:
                age = int(digits.group())
                age_source = _evidence(line)
        elif key == "sex":
            sex = _SEX_MAP.get(value.strip().lower(), Sex.UNKNOWN)

    return Patient(
        patient_id=patient_id,
        age=age,
        age_source=age_source,
        sex=sex,
        conditions=_parse_conditions(sections["conditions"]),
        medications=_parse_medications(sections["medications"]),
        labs=_parse_labs(sections["labs"]),
    )


def _parse_conditions(lines: list[TextLine]) -> list[Condition]:
    conditions: list[Condition] = []
    for line in lines:
        bullet = _BULLET.match(line.text)
        if not bullet:
            continue
        conditions.append(
            Condition(
                name=bullet.group(1).strip(),
                status=ClinicalStatus.ACTIVE,
                source=_evidence(line),
            )
        )
    return conditions


def _parse_medications(lines: list[TextLine]) -> list[Medication]:
    """Bulleted names, with an optional 'Duration:' line attaching to the previous drug."""
    medications: list[Medication] = []
    for line in lines:
        bullet = _BULLET.match(line.text)
        if bullet:
            medications.append(
                Medication(
                    name=bullet.group(1).strip(),
                    status=ClinicalStatus.ACTIVE,
                    source=_evidence(line),
                )
            )
            continue
        key_value = _KEY_VALUE.match(line.text)
        if key_value and key_value.group(1).strip().lower() == "duration" and medications:
            medications[-1] = medications[-1].model_copy(
                update={"duration_text": key_value.group(2).strip()}
            )
    return medications


def _parse_labs(lines: list[TextLine]) -> list[LabResult]:
    labs: list[LabResult] = []
    for line in lines:
        match = _LAB.match(line.text)
        if not match:
            continue
        unit = (match.group("unit") or "").strip()
        labs.append(
            LabResult(
                name=match.group("name").strip(),
                value=float(match.group("value")),
                unit=unit,
                observed_at=(match.group("date") or "").strip() or None,
                source=_evidence(line),
            )
        )
    return labs


# -- trial ----------------------------------------------------------------


def _build_trial(sections: dict[str, list[TextLine]]) -> Trial:
    trial_id = ""
    title = ""

    for line in sections["trial"]:
        match = _KEY_VALUE.match(line.text)
        if not match:
            continue
        key, value = match.group(1).strip().lower(), match.group(2).strip()
        if key in {"trial id", "trial identifier", "nct id"}:
            trial_id = value
        elif key == "title":
            title = value

    criteria = [
        *_parse_criteria(sections["inclusion"], CriterionKind.INCLUSION, "INC"),
        *_parse_criteria(sections["exclusion"], CriterionKind.EXCLUSION, "EXC"),
    ]

    return Trial(trial_id=trial_id, title=title or trial_id, criteria=criteria)


def _parse_criteria(
    lines: list[TextLine], kind: CriterionKind, prefix: str
) -> list[Criterion]:
    criteria: list[Criterion] = []
    for line in lines:
        bullet = _BULLET.match(line.text)
        if not bullet:
            continue
        text = bullet.group(1).strip()
        criteria.append(
            Criterion(
                criterion_id=f"{prefix}-{len(criteria) + 1:02d}",
                kind=kind,
                text=text,
                # None here is a real answer: the criterion becomes UNKNOWN.
                rule=parse_criterion_text(text),
            )
        )
    return criteria
