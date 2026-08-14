"""Criterion parsing and document extraction."""

import pytest

from app.extraction.criterion_parser import parse_criterion_text
from app.extraction.errors import ExtractionError
from app.extraction.pdf_reader import read_lines
from app.schema.enums import Domain, NumericOp
from app.schema.trial import NumericRule, PresenceRule


@pytest.mark.parametrize(
    ("text", "field", "op", "low", "high"),
    [
        ("Age between 18 and 65 years", "age", NumericOp.BETWEEN, 18, 65),
        ("Age 18-65", "age", NumericOp.BETWEEN, 18, 65),
        ("HbA1c between 7 and 10 %", "lab:HbA1c", NumericOp.BETWEEN, 7, 10),
        ("eGFR at least 45 mL/min", "lab:eGFR", NumericOp.GTE, 45, None),
        ("eGFR >= 45", "lab:eGFR", NumericOp.GTE, 45, None),
        ("Age no more than 70", "age", NumericOp.LTE, 70, None),
        ("Age greater than 21", "age", NumericOp.GT, 21, None),
    ],
)
def test_numeric_criteria_parse(text, field, op, low, high):
    rule = parse_criterion_text(text)

    assert isinstance(rule, NumericRule)
    assert (rule.field, rule.op, rule.low, rule.high) == (field, op, low, high)


def test_units_are_read_from_the_text_not_assumed():
    rule = parse_criterion_text("HbA1c at least 53 mmol/mol")
    assert rule.unit == "mmol/mol"


@pytest.mark.parametrize(
    ("text", "domain", "target"),
    [
        ("Diagnosis: Type 2 Diabetes", Domain.CONDITION, "Type 2 Diabetes"),
        ("Medication: Metformin", Domain.MEDICATION, "Metformin"),
        ("Condition: Hypertension", Domain.CONDITION, "Hypertension"),
    ],
)
def test_presence_criteria_parse(text, domain, target):
    rule = parse_criterion_text(text)

    assert isinstance(rule, PresenceRule)
    assert rule.domain is domain
    assert rule.target == target


@pytest.mark.parametrize(
    "text",
    [
        "Prior exposure to investigational GLP-1 agonist within 6 months of screening",
        "Willing and able to provide informed consent",
        "Investigator considers the patient suitable",
        "",
    ],
)
def test_unsupported_criteria_return_none_rather_than_a_guess(text):
    assert parse_criterion_text(text) is None


def test_unlabelled_drug_name_is_not_guessed():
    """Without a Diagnosis:/Medication: label we do not invent a domain."""
    assert parse_criterion_text("Metformin") is None


def test_read_lines_rejects_non_pdf():
    with pytest.raises(ExtractionError) as exc:
        read_lines(b"plain text file")
    assert exc.value.code == "NOT_A_PDF"


def test_read_lines_rejects_empty():
    with pytest.raises(ExtractionError) as exc:
        read_lines(b"")
    assert exc.value.code == "EMPTY_FILE"
