"""Deterministic offline mock AI/SLM.

Design note on how disagreement arises honestly
-----------------------------------------------
The rule engine matches condition names *literally*: an exclusion for "severe
cardiovascular disease" does not match a recorded condition of "stable angina",
so the criterion passes. This mock does what a language model actually does
well — it expands terminology through a concept table — and therefore reaches
the opposite conclusion.

That is a real, reproducible difference in capability, not a scripted stunt.
The correct system behaviour is to surface it and stop, which is exactly what
the disagreement detector does. Neither layer silently wins.

No randomness anywhere: same input, same output, every run.
"""

from __future__ import annotations

from .provider import AIProvider
from ..schema.clinical import Patient
from ..schema.enums import AIVerdict, CriterionKind, CriterionStatus, Domain
from ..schema.result import AIAnalysis, AICriterionOpinion, CriterionResult
from ..schema.trial import NumericRule, PresenceRule, Trial, normalize_term

# Small hand-written concept table. This is the mock's entire "understanding" —
# it stands in for what a real SLM would infer from language.
CONCEPT_TERMS: dict[str, tuple[str, ...]] = {
    "cardiovascular disease": (
        "angina",
        "stable angina",
        "unstable angina",
        "myocardial infarction",
        "heart failure",
        "coronary artery disease",
        "arrhythmia",
        "atrial fibrillation",
        "cardiomyopathy",
    ),
    "type 2 diabetes": (
        "t2dm",
        "type ii diabetes",
        "diabetes mellitus type 2",
        "niddm",
        "adult-onset diabetes",
    ),
    "renal impairment": (
        "chronic kidney disease",
        "ckd",
        "nephropathy",
        "renal insufficiency",
        "kidney disease",
    ),
    "hepatic impairment": ("cirrhosis", "liver disease", "hepatitis", "fatty liver"),
    "pregnancy": ("pregnant", "gestation", "breastfeeding", "lactating"),
    "malignancy": ("cancer", "carcinoma", "tumour", "tumor", "neoplasm", "lymphoma"),
    "insulin therapy": ("insulin glargine", "insulin aspart", "basal insulin"),
}

CONF_DIRECT = 0.94
CONF_CONCEPT = 0.78
CONF_NUMERIC = 0.96
CONF_WEAK = 0.55


class MockAIProvider(AIProvider):
    """Offline, deterministic, advisory."""

    name = "mock-slm-v1"

    def analyze(
        self,
        patient: Patient,
        trial: Trial,
        criteria_results: list[CriterionResult],
    ) -> AIAnalysis:
        try:
            opinions = self._opinions(patient, trial, criteria_results)
            return AIAnalysis(
                provider=self.name,
                opinions=opinions,
                summary=self._summary(criteria_results, opinions),
            )
        except Exception as exc:  # noqa: BLE001 - advisory layer must never abort screening
            return AIAnalysis(
                provider=self.name,
                opinions=[],
                summary=f"AI analysis unavailable ({type(exc).__name__}). "
                "Screening completed using deterministic rules only.",
                degraded=True,
            )

    # -- opinions ---------------------------------------------------------

    def _opinions(
        self,
        patient: Patient,
        trial: Trial,
        criteria_results: list[CriterionResult],
    ) -> list[AICriterionOpinion]:
        by_id = {c.criterion_id: c for c in trial.criteria}
        patient_terms = _patient_terms(patient)
        opinions: list[AICriterionOpinion] = []

        for result in criteria_results:
            criterion = by_id.get(result.criterion_id)
            if criterion is None:
                continue
            if isinstance(criterion.rule, NumericRule):
                opinion = self._numeric_opinion(result)
            else:
                opinion = self._terminology_opinion(criterion, result, patient_terms)
            if opinion is not None:
                opinions.append(opinion)
        return opinions

    def _numeric_opinion(self, result: CriterionResult) -> AICriterionOpinion | None:
        """Restate the arithmetic. The mock has no reason to doubt a number."""
        if result.status is CriterionStatus.UNKNOWN:
            return AICriterionOpinion(
                criterion_id=result.criterion_id,
                verdict=AIVerdict.AMBIGUOUS,
                confidence=CONF_WEAK,
                rationale=(
                    "The required measurement is missing or reported in an "
                    "incompatible unit, so the threshold cannot be checked."
                ),
            )
        verdict = (
            AIVerdict.SUPPORTED
            if result.status is CriterionStatus.PASS
            else AIVerdict.NOT_SUPPORTED
        )
        return AICriterionOpinion(
            criterion_id=result.criterion_id,
            verdict=verdict,
            confidence=CONF_NUMERIC,
            rationale=(
                f"Observed {result.observed} against requirement "
                f"'{result.expected}'."
            ),
        )

    def _terminology_opinion(
        self,
        criterion,
        result: CriterionResult,
        patient_terms: dict[Domain, set[str]],
    ) -> AICriterionOpinion:
        """Concept-level matching — where the mock can outrun, or contradict, the rules."""
        target = _criterion_target(criterion)
        domain = (
            criterion.rule.domain
            if isinstance(criterion.rule, PresenceRule)
            else Domain.CONDITION
        )
        haystack = patient_terms[domain] | patient_terms[Domain.MEDICATION]

        if not haystack:
            return AICriterionOpinion(
                criterion_id=result.criterion_id,
                verdict=AIVerdict.AMBIGUOUS,
                confidence=CONF_WEAK,
                rationale="The record contains no entries to interpret for this criterion.",
            )

        direct = target in haystack
        concept_hits = sorted(_concept_hits(target, haystack))

        if direct:
            matched, confidence = True, CONF_DIRECT
            evidence_text = f"'{target}' is recorded directly."
        elif concept_hits:
            matched, confidence = True, CONF_CONCEPT
            evidence_text = (
                f"'{', '.join(concept_hits)}' is recorded, which falls under "
                f"the concept '{target}'."
            )
        else:
            matched, confidence = False, CONF_CONCEPT
            evidence_text = f"No entry corresponding to '{target}' was found."

        # Same inversion the rule engine applies, so the two verdicts are
        # directly comparable.
        satisfied = matched if criterion.kind is CriterionKind.INCLUSION else not matched
        return AICriterionOpinion(
            criterion_id=result.criterion_id,
            verdict=AIVerdict.SUPPORTED if satisfied else AIVerdict.NOT_SUPPORTED,
            confidence=confidence,
            rationale=evidence_text,
        )

    def _summary(
        self,
        criteria_results: list[CriterionResult],
        opinions: list[AICriterionOpinion],
    ) -> str:
        unknown = sum(1 for r in criteria_results if r.status is CriterionStatus.UNKNOWN)
        ambiguous = sum(1 for o in opinions if o.verdict is AIVerdict.AMBIGUOUS)
        parts = [
            f"Reviewed {len(criteria_results)} criteria; "
            f"produced {len(opinions)} advisory opinions."
        ]
        if unknown:
            parts.append(
                f"{unknown} could not be verified deterministically and need human review."
            )
        if ambiguous:
            parts.append(f"{ambiguous} remain ambiguous after interpretation.")
        parts.append("These opinions are advisory and do not determine eligibility.")
        return " ".join(parts)


# -- helpers --------------------------------------------------------------


def _patient_terms(patient: Patient) -> dict[Domain, set[str]]:
    return {
        Domain.CONDITION: {normalize_term(c.name) for c in patient.conditions},
        Domain.MEDICATION: {normalize_term(m.name) for m in patient.medications},
    }


def _criterion_target(criterion) -> str:
    if isinstance(criterion.rule, PresenceRule):
        return normalize_term(criterion.rule.target)
    # Unsupported criterion: fall back to the criterion's own wording, with
    # common negation/boilerplate stripped so concept lookup has a fair chance.
    text = normalize_term(criterion.text)
    for prefix in ("no ", "not ", "absence of ", "history of ", "prior ", "previous "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.strip()


def _concept_hits(target: str, haystack: set[str]) -> set[str]:
    """Patient entries that map to the target concept via the concept table."""
    hits: set[str] = set()
    for concept, members in CONCEPT_TERMS.items():
        # The criterion names the concept (or the concept names the criterion).
        if concept not in target and target not in concept:
            continue
        normalized = {normalize_term(m) for m in members}
        hits |= haystack & normalized
    return hits
