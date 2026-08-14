"""Result-side canonical models.

Note the asymmetry that encodes the AI boundary: `CriterionResult` has no
field the AI layer is allowed to write. AI output lives entirely in
`AIAnalysis` and `Disagreement`, which are siblings of the criteria results,
never parents of them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from .clinical import Evidence, Patient
from .enums import (
    AIVerdict,
    CriterionKind,
    CriterionStatus,
    HeuristicCode,
    OverallStatus,
    Severity,
)
from .trial import Trial


class CriterionResult(BaseModel):
    """The deterministic engine's verdict on one criterion. Authoritative."""

    criterion_id: str
    kind: CriterionKind
    text: str
    status: CriterionStatus
    # Did the underlying rule match, before inclusion/exclusion inversion?
    # None when the rule could not be evaluated. Shown in the report so a
    # reviewer can see the inversion was applied correctly.
    raw_match: bool | None = None
    expected: str
    observed: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    evaluator: str = "RULE_ENGINE"


class HeuristicFlag(BaseModel):
    code: HeuristicCode
    severity: Severity
    message: str
    criterion_ids: list[str] = Field(default_factory=list)


class AICriterionOpinion(BaseModel):
    criterion_id: str
    verdict: AIVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class AIAnalysis(BaseModel):
    provider: str
    opinions: list[AICriterionOpinion] = Field(default_factory=list)
    summary: str = ""
    # True when the provider failed and we returned an empty advisory result
    # rather than aborting the screening.
    degraded: bool = False


class Disagreement(BaseModel):
    criterion_id: str
    rule_status: CriterionStatus
    ai_verdict: AIVerdict
    description: str


class ScreeningResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    result_id: str
    patient: Patient
    trial: Trial
    overall_status: OverallStatus
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    unknown_count: int = 0
    # Fraction of criteria the deterministic engine could express as a rule.
    # An honest measure of how much of this screening was actually verified.
    rule_coverage: float = 0.0
    heuristic_flags: list[HeuristicFlag] = Field(default_factory=list)
    ai_analysis: AIAnalysis | None = None
    disagreements: list[Disagreement] = Field(default_factory=list)
    # Why the overall status came out the way it did, in order of precedence.
    status_reason: str = ""
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
