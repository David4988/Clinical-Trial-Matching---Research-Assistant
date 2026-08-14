"""Canonical clinical schema — the central architectural boundary.

Everything upstream (PDF today, LLM/OCR/API/CSV later) converges here.
Everything downstream (rules, heuristics, AI, persistence, report) consumes
only these types. The screening engine must never learn where the data
came from.
"""

from .clinical import Condition, Evidence, LabResult, Medication, Patient
from .enums import (
    AIVerdict,
    ClinicalStatus,
    CriterionKind,
    CriterionStatus,
    Domain,
    EvidenceSource,
    HeuristicCode,
    NumericOp,
    OverallStatus,
    Severity,
    Sex,
)
from .result import (
    AIAnalysis,
    AICriterionOpinion,
    CriterionResult,
    Disagreement,
    HeuristicFlag,
    ScreeningResult,
)
from .trial import (
    LAB_PREFIX,
    Criterion,
    NumericRule,
    PresenceRule,
    Rule,
    Trial,
    normalize_term,
)

__all__ = [
    "AIAnalysis",
    "AICriterionOpinion",
    "AIVerdict",
    "ClinicalStatus",
    "Condition",
    "Criterion",
    "CriterionKind",
    "CriterionResult",
    "CriterionStatus",
    "Disagreement",
    "Domain",
    "Evidence",
    "EvidenceSource",
    "HeuristicCode",
    "HeuristicFlag",
    "LAB_PREFIX",
    "LabResult",
    "Medication",
    "NumericOp",
    "NumericRule",
    "OverallStatus",
    "Patient",
    "PresenceRule",
    "Rule",
    "ScreeningResult",
    "Severity",
    "Sex",
    "Trial",
    "normalize_term",
]
