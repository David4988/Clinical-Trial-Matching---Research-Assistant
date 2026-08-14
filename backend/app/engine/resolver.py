"""Resolve rule field references against a patient record.

Separated from the evaluators so that "can we find this value?" and "does this
value satisfy the rule?" stay independently testable. The resolver never makes
a judgement — it only reports what the record contains, and says so plainly
when it contains nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from ..schema.clinical import Evidence, LabResult, Patient
from ..schema.enums import Domain, EvidenceSource
from ..schema.trial import LAB_PREFIX, normalize_term

# Only pure notational variants belong here. Anything requiring arithmetic
# (mg/dL -> mmol/L) is a real conversion and must NOT be silently applied;
# such a criterion resolves to UNKNOWN instead. See docs/ARCHITECTURE.md.
_UNIT_ALIASES: dict[str, str] = {
    "%": "%",
    "percent": "%",
    "pct": "%",
    "years": "years",
    "year": "years",
    "yrs": "years",
    "y": "years",
}


def canonical_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    cleaned = normalize_term(unit)
    if not cleaned:
        return None
    return _UNIT_ALIASES.get(cleaned, cleaned)


def units_compatible(required: str | None, observed: str | None) -> bool:
    """True when the units agree, or when either side asserts no unit."""
    req, obs = canonical_unit(required), canonical_unit(observed)
    if req is None or obs is None:
        return True
    return req == obs


@dataclass
class NumericResolution:
    found: bool
    label: str
    value: float | None = None
    unit: str | None = None
    evidence: list[Evidence] = dc_field(default_factory=list)
    reason: str | None = None
    # Every lab row matching the name, in document order. Heuristics use this
    # to spot a record that reports the same analyte twice with different
    # values; evaluation uses only the last one.
    all_matches: list[LabResult] = dc_field(default_factory=list)


def resolve_numeric_field(patient: Patient, field: str) -> NumericResolution:
    if field == "age":
        if patient.age is None:
            return NumericResolution(
                found=False, label="age", reason="Patient age not recorded"
            )
        return NumericResolution(
            found=True,
            label="age",
            value=float(patient.age),
            unit="years",
            evidence=[
                patient.age_source
                or Evidence(
                    source_type=EvidenceSource.PDF_FIELD,
                    locator="patient.age",
                    snippet=f"Age: {patient.age}",
                )
            ],
        )

    if not field.startswith(LAB_PREFIX):
        return NumericResolution(
            found=False, label=field, reason=f"Unsupported field reference '{field}'"
        )

    lab_name = field[len(LAB_PREFIX):]
    wanted = normalize_term(lab_name)
    matches = [lab for lab in patient.labs if normalize_term(lab.name) == wanted]

    if not matches:
        return NumericResolution(
            found=False,
            label=lab_name,
            reason=f"No {lab_name} result available for this patient",
        )

    # Last occurrence wins: extractors emit labs in document order and clinical
    # documents list results oldest-first. Duplicates are surfaced by the
    # contradictory-data heuristic rather than silently resolved here.
    latest = matches[-1]
    observed_at = f" ({latest.observed_at})" if latest.observed_at else ""
    return NumericResolution(
        found=True,
        label=latest.name,
        value=latest.value,
        unit=latest.unit,
        all_matches=matches,
        evidence=[
            latest.source
            or Evidence(
                source_type=EvidenceSource.LAB,
                locator=f"labs.{latest.name}",
                snippet=f"{latest.name}: {latest.value} {latest.unit}{observed_at}",
            )
        ],
    )


@dataclass
class PresenceResolution:
    # None means "the record does not tell us" — distinct from False, which
    # means "the record tells us this is absent".
    matched: bool | None
    observed: str
    evidence: list[Evidence] = dc_field(default_factory=list)
    reason: str | None = None


def resolve_presence(
    patient: Patient, domain: Domain, terms: list[str]
) -> PresenceResolution:
    if domain is Domain.CONDITION:
        entries = [(c.name, c.source, EvidenceSource.CONDITION) for c in patient.conditions]
        domain_label = "condition"
    else:
        entries = [(m.name, m.source, EvidenceSource.MEDICATION) for m in patient.medications]
        domain_label = "medication"

    # An empty list is ambiguous: it could mean "none" or "not documented".
    # Refusing to read it as "absent" is what keeps the engine honest.
    if not entries:
        return PresenceResolution(
            matched=None,
            observed="No data recorded",
            reason=f"No {domain_label} history available for this patient",
        )

    wanted = set(terms)
    hits = [
        (name, source, src_type)
        for name, source, src_type in entries
        if normalize_term(name) in wanted
    ]

    if hits:
        return PresenceResolution(
            matched=True,
            observed=", ".join(name for name, _, _ in hits),
            evidence=[
                source
                or Evidence(
                    source_type=src_type,
                    locator=f"{domain_label}s.{name}",
                    snippet=name,
                )
                for name, source, src_type in hits
            ],
        )

    # A negative finding has no single source line, so cite the whole search:
    # a summary plus every entry that was checked. Without this, "Not present"
    # would be the one verdict in the report a reviewer could not audit.
    recorded = ", ".join(name for name, _, _ in entries)
    searched_sources = [source for _, source, _ in entries if source is not None]
    return PresenceResolution(
        matched=False,
        observed="Not present",
        evidence=[
            Evidence(
                source_type=EvidenceSource.RULE,
                locator=f"{domain_label}s",
                snippet=f"Recorded {domain_label}s: {recorded}",
                note=f"Searched all {len(entries)} recorded {domain_label}s; no match found.",
            ),
            *searched_sources,
        ],
    )
