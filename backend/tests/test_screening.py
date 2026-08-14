"""End-to-end screening cases against the canonical fixtures.

These are the acceptance cases for Phase 1. They run with no PDF and no
network — the point of the canonical boundary.
"""

from app.fixtures_loader import load_patient, load_trial
from app.schema.enums import (
    AIVerdict,
    CriterionStatus,
    HeuristicCode,
    OverallStatus,
    Severity,
)


def _status_of(result, criterion_id):
    return next(r.status for r in result.criteria_results if r.criterion_id == criterion_id)


def test_case1_all_criteria_pass_is_eligible(service):
    result = service.screen(load_patient("patient_eligible"), load_trial("trial_supported"))

    assert result.overall_status is OverallStatus.ELIGIBLE
    assert result.failed_count == 0
    assert result.unknown_count == 0
    assert result.passed_count == 6
    assert result.rule_coverage == 1.0
    assert result.disagreements == []


def test_case2_one_failure_is_ineligible(service):
    result = service.screen(load_patient("patient_ineligible"), load_trial("trial_supported"))

    assert result.overall_status is OverallStatus.INELIGIBLE
    assert _status_of(result, "INC-04") is CriterionStatus.FAIL  # eGFR 38 < 45


def test_case2b_fail_dominates_unknown(service):
    """P-2087 has both a failing eGFR and an unrecorded medication list."""
    result = service.screen(load_patient("patient_ineligible"), load_trial("trial_supported"))

    assert result.failed_count >= 1
    assert result.unknown_count >= 1
    assert result.overall_status is OverallStatus.INELIGIBLE


def test_case3_missing_information_is_review_required(service):
    result = service.screen(load_patient("patient_incomplete"), load_trial("trial_supported"))

    assert result.overall_status is OverallStatus.REVIEW_REQUIRED
    assert result.failed_count == 0
    assert _status_of(result, "INC-04") is CriterionStatus.UNKNOWN  # eGFR absent
    assert any(f.code is HeuristicCode.MISSING_FIELD for f in result.heuristic_flags)


def test_case5_ai_rule_disagreement_forces_review(service):
    """Rule engine passes EXC-01 literally; the AI maps Stable Angina to the concept."""
    result = service.screen(load_patient("patient_disagreement"), load_trial("trial_supported"))

    assert result.overall_status is OverallStatus.REVIEW_REQUIRED
    assert len(result.disagreements) == 1

    disagreement = result.disagreements[0]
    assert disagreement.criterion_id == "EXC-01"
    assert disagreement.rule_status is CriterionStatus.PASS
    assert disagreement.ai_verdict is AIVerdict.NOT_SUPPORTED

    # The rule verdict itself must be untouched by the AI's objection.
    assert _status_of(result, "EXC-01") is CriterionStatus.PASS


def test_case8_unit_mismatch_is_unknown_with_warning(service):
    result = service.screen(load_patient("patient_unit_mismatch"), load_trial("trial_supported"))

    assert _status_of(result, "INC-03") is CriterionStatus.UNKNOWN
    assert result.overall_status is OverallStatus.REVIEW_REQUIRED

    flags = [f for f in result.heuristic_flags if f.code is HeuristicCode.UNIT_MISMATCH]
    assert len(flags) == 1
    assert flags[0].severity is Severity.WARN


def test_case9_unsupported_criterion_is_unknown_and_gets_ai_opinion(service):
    """trial_demo's EXC-02 has rule=None and must never be guessed."""
    result = service.screen(load_patient("patient_eligible"), load_trial("trial_demo"))

    assert _status_of(result, "EXC-02") is CriterionStatus.UNKNOWN
    assert result.rule_coverage < 1.0
    assert any(
        f.code is HeuristicCode.UNSUPPORTED_CRITERION for f in result.heuristic_flags
    )

    opinion = next(
        o for o in result.ai_analysis.opinions if o.criterion_id == "EXC-02"
    )
    assert opinion.verdict in set(AIVerdict)


def test_ai_never_changes_a_rule_verdict(service):
    """Structural check: every criterion result is attributed to the rule engine."""
    for patient_name in (
        "patient_eligible",
        "patient_ineligible",
        "patient_incomplete",
        "patient_disagreement",
        "patient_unit_mismatch",
    ):
        result = service.screen(load_patient(patient_name), load_trial("trial_demo"))
        assert all(r.evaluator == "RULE_ENGINE" for r in result.criteria_results)


def test_mock_ai_is_deterministic(service):
    a = service.screen(load_patient("patient_disagreement"), load_trial("trial_demo"))
    b = service.screen(load_patient("patient_disagreement"), load_trial("trial_demo"))

    assert a.ai_analysis.model_dump() == b.ai_analysis.model_dump()
    assert a.overall_status is b.overall_status


def test_borderline_value_is_flagged(service):
    """P-1042's eGFR of 47 sits just above the floor of 45."""
    result = service.screen(load_patient("patient_pdf_demo"), load_trial("trial_demo"))

    assert _status_of(result, "INC-04") is CriterionStatus.PASS
    assert any(f.code is HeuristicCode.BORDERLINE_VALUE for f in result.heuristic_flags)


def test_contradictory_duplicate_labs_are_flagged(service):
    result = service.screen(load_patient("patient_pdf_demo"), load_trial("trial_demo"))

    assert any(
        f.code is HeuristicCode.CONTRADICTORY_DATA for f in result.heuristic_flags
    )


def test_every_criterion_result_carries_evidence(service):
    result = service.screen(load_patient("patient_pdf_demo"), load_trial("trial_demo"))

    for criterion_result in result.criteria_results:
        assert criterion_result.evidence, f"{criterion_result.criterion_id} has no evidence"
        assert criterion_result.expected
