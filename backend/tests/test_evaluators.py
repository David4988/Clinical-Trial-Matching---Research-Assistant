"""Numeric evaluation: operators, boundaries, and unit safety."""

import pytest

from app.engine.evaluators import evaluate_numeric
from app.schema.clinical import LabResult, Patient
from app.schema.enums import NumericOp
from app.schema.trial import NumericRule


def _patient(age=None, labs=None) -> Patient:
    return Patient(patient_id="P-TEST", age=age, labs=labs or [])


@pytest.mark.parametrize(
    ("op", "low", "high", "value", "expected"),
    [
        (NumericOp.GTE, 18, None, 18, True),   # Case 4: inclusive boundary
        (NumericOp.GTE, 18, None, 17, False),
        (NumericOp.GT, 18, None, 18, False),
        (NumericOp.LTE, 65, None, 65, True),
        (NumericOp.LT, 65, None, 65, False),
        (NumericOp.EQ, 40, None, 40, True),
        (NumericOp.BETWEEN, 18, 65, 18, True),  # both ends inclusive
        (NumericOp.BETWEEN, 18, 65, 65, True),
        (NumericOp.BETWEEN, 18, 65, 66, False),
    ],
)
def test_numeric_operators_and_boundaries(op, low, high, value, expected):
    rule = NumericRule(field="age", op=op, low=low, high=high, unit="years")
    assert evaluate_numeric(rule, _patient(age=value)).match is expected


def test_missing_value_is_unresolved():
    rule = NumericRule(field="lab:eGFR", op=NumericOp.GTE, low=45, unit="mL/min")
    outcome = evaluate_numeric(rule, _patient(age=50))

    assert outcome.match is None
    assert "eGFR" in outcome.reason


def test_unit_mismatch_never_converts_silently():
    """Case 8: mmol/mol is not % — refuse rather than guess."""
    rule = NumericRule(field="lab:HbA1c", op=NumericOp.BETWEEN, low=7, high=10, unit="%")
    patient = _patient(labs=[LabResult(name="HbA1c", value=66, unit="mmol/mol")])
    outcome = evaluate_numeric(rule, patient)

    assert outcome.match is None
    assert outcome.unit_mismatch is True


def test_notational_unit_variants_are_accepted():
    rule = NumericRule(field="lab:HbA1c", op=NumericOp.BETWEEN, low=7, high=10, unit="%")
    patient = _patient(labs=[LabResult(name="HbA1c", value=8.2, unit="percent")])

    assert evaluate_numeric(rule, patient).match is True


def test_latest_duplicate_lab_wins():
    rule = NumericRule(field="lab:HbA1c", op=NumericOp.BETWEEN, low=7, high=10, unit="%")
    patient = _patient(
        labs=[
            LabResult(name="HbA1c", value=12.0, unit="%", observed_at="2025-01-01"),
            LabResult(name="HbA1c", value=8.2, unit="%", observed_at="2026-03-11"),
        ]
    )
    outcome = evaluate_numeric(rule, patient)

    assert outcome.match is True
    assert "8.2" in outcome.observed


def test_between_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        NumericRule(field="age", op=NumericOp.BETWEEN, low=65, high=18)
