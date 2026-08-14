"""The inclusion/exclusion inversion table.

Getting this backwards turns "patient has an excluded condition" into a green
tick, so it gets exhaustive coverage rather than a spot check.
"""

import pytest

from app.engine.eligibility import apply_inversion, evaluate_criterion
from app.schema.clinical import Condition, Patient
from app.schema.enums import ClinicalStatus, CriterionKind, CriterionStatus, Domain
from app.schema.trial import Criterion, PresenceRule


@pytest.mark.parametrize(
    ("kind", "matched", "expected"),
    [
        (CriterionKind.INCLUSION, True, CriterionStatus.PASS),
        (CriterionKind.INCLUSION, False, CriterionStatus.FAIL),
        (CriterionKind.INCLUSION, None, CriterionStatus.UNKNOWN),
        (CriterionKind.EXCLUSION, True, CriterionStatus.FAIL),
        (CriterionKind.EXCLUSION, False, CriterionStatus.PASS),
        (CriterionKind.EXCLUSION, None, CriterionStatus.UNKNOWN),
    ],
)
def test_inversion_table(kind, matched, expected):
    assert apply_inversion(kind, matched) is expected


def _patient_with(*condition_names: str) -> Patient:
    return Patient(
        patient_id="P-TEST",
        age=40,
        conditions=[
            Condition(name=n, status=ClinicalStatus.ACTIVE) for n in condition_names
        ],
    )


def test_exclusion_matched_is_fail_not_pass():
    """Case 7: the patient HAS the excluded condition."""
    criterion = Criterion(
        criterion_id="EXC-X",
        kind=CriterionKind.EXCLUSION,
        text="Severe cardiovascular disease",
        rule=PresenceRule(domain=Domain.CONDITION, target="Severe cardiovascular disease"),
    )
    result = evaluate_criterion(criterion, _patient_with("Severe cardiovascular disease"))

    assert result.raw_match is True
    assert result.status is CriterionStatus.FAIL


def test_exclusion_absent_is_pass():
    criterion = Criterion(
        criterion_id="EXC-X",
        kind=CriterionKind.EXCLUSION,
        text="Severe cardiovascular disease",
        rule=PresenceRule(domain=Domain.CONDITION, target="Severe cardiovascular disease"),
    )
    result = evaluate_criterion(criterion, _patient_with("Type 2 Diabetes"))

    assert result.raw_match is False
    assert result.status is CriterionStatus.PASS


def test_empty_domain_is_unknown_not_absent():
    """An empty medication list means 'not documented', never 'not taking it'."""
    criterion = Criterion(
        criterion_id="EXC-Y",
        kind=CriterionKind.EXCLUSION,
        text="Prior exposure to Trial Drug X",
        rule=PresenceRule(domain=Domain.MEDICATION, target="Trial Drug X"),
    )
    result = evaluate_criterion(criterion, Patient(patient_id="P-TEST", age=40))

    assert result.raw_match is None
    assert result.status is CriterionStatus.UNKNOWN
