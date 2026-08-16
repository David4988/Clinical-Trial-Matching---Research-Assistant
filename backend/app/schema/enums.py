"""Canonical enumerations.

These names appear in API responses and in the frontend types. Changing a value
here is a breaking contract change.
"""

from enum import Enum


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class CriterionKind(str, Enum):
    INCLUSION = "INCLUSION"
    EXCLUSION = "EXCLUSION"


class CriterionStatus(str, Enum):
    """Per-criterion verdict.

    PASS always means "the patient satisfies this criterion for enrollment",
    for inclusion and exclusion criteria alike. See engine/eligibility.py for
    the inversion table.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class OverallStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EvidenceSource(str, Enum):
    PDF_FIELD = "PDF_FIELD"
    LAB = "LAB"
    MEDICATION = "MEDICATION"
    CONDITION = "CONDITION"
    RULE = "RULE"
    AI = "AI"
    # Phase 2 additions. Additive only — no existing value changed, so the
    # Phase 1 contract is untouched. A vital sign is not a LAB, and a risk
    # model is not the Phase 1 AI layer, so both get their own source.
    OBSERVATION = "OBSERVATION"
    RISK_MODEL = "RISK_MODEL"


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"


class AIVerdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"


class ClinicalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST = "PAST"
    RESOLVED = "RESOLVED"
    UNKNOWN = "UNKNOWN"


class NumericOp(str, Enum):
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"
    EQ = "eq"
    BETWEEN = "between"


class Domain(str, Enum):
    CONDITION = "condition"
    MEDICATION = "medication"


class HeuristicCode(str, Enum):
    MISSING_FIELD = "MISSING_FIELD"
    UNSUPPORTED_CRITERION = "UNSUPPORTED_CRITERION"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    BORDERLINE_VALUE = "BORDERLINE_VALUE"
    CONTRADICTORY_DATA = "CONTRADICTORY_DATA"
    INCOMPLETE_RECORD = "INCOMPLETE_RECORD"
    LOW_RULE_COVERAGE = "LOW_RULE_COVERAGE"
