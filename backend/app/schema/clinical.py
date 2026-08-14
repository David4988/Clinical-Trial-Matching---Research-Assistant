"""Patient-side canonical models.

This module records *observations about a patient*. It knows nothing about
trials, rules, PDFs, or storage. Every extraction adapter (PDF today; LLM and
OCR in later phases) must produce exactly these types.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import ClinicalStatus, EvidenceSource, Sex


class Evidence(BaseModel):
    """Provenance for a single fact or decision.

    `locator` is deliberately a free-form string so that each adapter can use
    whatever addressing it naturally has: "page 1, line 12" for PDF, a JSON
    pointer for API input, a cell reference for CSV.
    """

    model_config = ConfigDict(frozen=True)

    source_type: EvidenceSource
    locator: str | None = None
    snippet: str | None = None
    note: str | None = None


class Condition(BaseModel):
    name: str
    icd10: str | None = None
    status: ClinicalStatus = ClinicalStatus.UNKNOWN
    source: Evidence | None = None


class Medication(BaseModel):
    name: str
    rxnorm: str | None = None
    status: ClinicalStatus = ClinicalStatus.UNKNOWN
    duration_text: str | None = None
    source: Evidence | None = None


class LabResult(BaseModel):
    name: str
    value: float
    unit: str
    # Free-form on purpose: the demo PDFs use mixed date formats and Phase 1
    # never does date arithmetic. Normalising this is Phase 2 work.
    observed_at: str | None = None
    source: Evidence | None = None


class Patient(BaseModel):
    patient_id: str
    age: int | None = None
    # Demographics are scalars, so they cannot carry their own `source` the way
    # conditions, medications and labs do. Age is the only one criteria are
    # evaluated against, so it gets an explicit provenance slot — otherwise an
    # age verdict would be the one result in the report with no traceable origin.
    age_source: Evidence | None = None
    sex: Sex = Sex.UNKNOWN
    conditions: list[Condition] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    labs: list[LabResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
