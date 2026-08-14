"""Trial-side canonical models and the Phase 1 rule vocabulary.

The rule vocabulary is deliberately tiny: two rule shapes, six numeric
operators, two presence domains. It is NOT a general rule language, and it
should not grow into one. A criterion the parser cannot express in this
vocabulary keeps `rule = None` and is evaluated as UNKNOWN — never guessed.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import CriterionKind, Domain, NumericOp

# Field addressing for numeric rules:
#   "age"          -> Patient.age
#   "lab:<name>"   -> the most recent LabResult whose name matches <name>
LAB_PREFIX = "lab:"


def normalize_term(term: str) -> str:
    """Casefold and collapse whitespace so lookups are stable.

    Used for lab names, condition names and medication names alike. This is the
    only "normalisation" the deterministic layer does — anything cleverer
    (synonyms, ontologies) is the AI layer's job and stays advisory.
    """
    return " ".join(term.split()).casefold()


class NumericRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["numeric"] = "numeric"
    field: str
    op: NumericOp
    low: float | None = None
    high: float | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _check_bounds(self) -> NumericRule:
        if self.op is NumericOp.BETWEEN:
            if self.low is None or self.high is None:
                raise ValueError("between requires both low and high")
            if self.low > self.high:
                raise ValueError("between requires low <= high")
        elif self.low is None:
            raise ValueError(f"{self.op.value} requires low")
        return self

    def describe(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        name = self.field[len(LAB_PREFIX):] if self.field.startswith(LAB_PREFIX) else self.field
        if self.op is NumericOp.BETWEEN:
            return f"{name} between {_num(self.low)} and {_num(self.high)}{unit}"
        symbol = {
            NumericOp.GTE: ">=",
            NumericOp.GT: ">",
            NumericOp.LTE: "<=",
            NumericOp.LT: "<",
            NumericOp.EQ: "==",
        }[self.op]
        return f"{name} {symbol} {_num(self.low)}{unit}"


class PresenceRule(BaseModel):
    """Does the patient have <target> in <domain>?

    Note this rule only answers the *match* question. Whether a match is good
    or bad for enrollment is decided by the criterion's INCLUSION/EXCLUSION
    kind, not here. Keeping those two concerns apart is what makes the
    inversion table in engine/eligibility.py the single place to get it right.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal["presence"] = "presence"
    domain: Domain
    target: str
    synonyms: tuple[str, ...] = ()

    def all_terms(self) -> list[str]:
        return [normalize_term(t) for t in (self.target, *self.synonyms)]

    def describe(self) -> str:
        return f"{self.domain.value} '{self.target}' present"


Rule = Annotated[Union[NumericRule, PresenceRule], Field(discriminator="type")]


class Criterion(BaseModel):
    criterion_id: str
    kind: CriterionKind
    # Always the verbatim wording from the source document. The report shows
    # this, not the machine rule, so a reviewer can check our interpretation.
    text: str
    rule: Rule | None = None

    @property
    def is_supported(self) -> bool:
        return self.rule is not None

    def describe_expected(self) -> str:
        if self.rule is None:
            return "Not machine-evaluable"
        described = self.rule.describe()
        if self.kind is CriterionKind.EXCLUSION:
            return f"NOT ({described})"
        return described


class Trial(BaseModel):
    trial_id: str
    title: str
    criteria: list[Criterion] = Field(default_factory=list)


def _num(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else str(value)
