"""Criterion text -> structured rule, or None.

Returning None is a first-class outcome, not a failure. A criterion this
parser cannot express in the Phase 1 vocabulary keeps `rule = None`, becomes
UNKNOWN, and is referred to the advisory AI layer. Inventing a rule to avoid
an UNKNOWN would be the single most dangerous thing this module could do.

Presence criteria are recognised by an explicit "Diagnosis:" / "Medication:"
label rather than by guessing whether a word is a drug or a disease. Protocols
really are written that way, and it keeps a hidden drug dictionary — which
would silently misclassify anything not in it — out of the deterministic path.
Phase 2's LLM extractor is what removes this constraint.
"""

from __future__ import annotations

import re

from ..schema.enums import Domain, NumericOp
from ..schema.trial import NumericRule, PresenceRule, Rule

# Numeric fields the Phase 1 vocabulary understands, with their protocol unit.
_FIELD_ALIASES: dict[str, tuple[str, str]] = {
    "age": ("age", "years"),
    "hba1c": ("lab:HbA1c", "%"),
    "a1c": ("lab:HbA1c", "%"),
    "egfr": ("lab:eGFR", "mL/min"),
}

# Recognised unit spellings, mapped to their canonical written form.
_KNOWN_UNITS: dict[str, str] = {
    "%": "%",
    "percent": "%",
    "years": "years",
    "year": "years",
    "yrs": "years",
    "ml/min": "mL/min",
    "ml/min/1.73m2": "mL/min/1.73m2",
    "mmol/mol": "mmol/mol",
    "mmol/l": "mmol/L",
    "mg/dl": "mg/dL",
    "kg/m2": "kg/m2",
}

_NUM = r"(-?\d+(?:\.\d+)?)"

# Ordered: two-bound forms first, then the compound operators (>=, <=) before
# their single-character prefixes, so ">= 45" never parses as "> =45".
_NUMERIC_PATTERNS: list[tuple[re.Pattern[str], NumericOp]] = [
    (re.compile(rf"between\s+{_NUM}\s+(?:and|to)\s+{_NUM}"), NumericOp.BETWEEN),
    (re.compile(rf"{_NUM}\s*(?:-|–|—|to)\s*{_NUM}"), NumericOp.BETWEEN),
    (
        re.compile(
            rf"(?:>=|≥|at\s+least|minimum(?:\s+of)?|no\s+less\s+than|not\s+less\s+than)\s*{_NUM}"
        ),
        NumericOp.GTE,
    ),
    (
        re.compile(
            rf"(?:<=|≤|at\s+most|maximum(?:\s+of)?|no\s+more\s+than|not\s+more\s+than|up\s+to)\s*{_NUM}"
        ),
        NumericOp.LTE,
    ),
    (re.compile(rf"(?:>|greater\s+than|above|over)\s*{_NUM}"), NumericOp.GT),
    (re.compile(rf"(?:<|less\s+than|below|under)\s*{_NUM}"), NumericOp.LT),
    (re.compile(rf"(?:==|=|equal\s+to|exactly)\s*{_NUM}"), NumericOp.EQ),
]

_PRESENCE_LABELS: dict[str, Domain] = {
    "diagnosis": Domain.CONDITION,
    "condition": Domain.CONDITION,
    "medication": Domain.MEDICATION,
    "drug": Domain.MEDICATION,
    "therapy": Domain.MEDICATION,
}

_PRESENCE_PATTERN = re.compile(
    rf"^\s*({'|'.join(_PRESENCE_LABELS)})\s*:\s*(.+)$", re.IGNORECASE
)


def parse_criterion_text(text: str) -> Rule | None:
    """Best-effort structured rule for a criterion, or None if unsupported."""
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    return _parse_presence(cleaned) or _parse_numeric(cleaned)


def _parse_presence(text: str) -> PresenceRule | None:
    match = _PRESENCE_PATTERN.match(text)
    if not match:
        return None
    label, target = match.group(1).lower(), match.group(2).strip()
    if not target:
        return None
    return PresenceRule(domain=_PRESENCE_LABELS[label], target=target)


def _parse_numeric(text: str) -> NumericRule | None:
    lowered = text.lower()

    field_key = next(
        (alias for alias in sorted(_FIELD_ALIASES, key=len, reverse=True) if alias in lowered),
        None,
    )
    if field_key is None:
        return None
    field, default_unit = _FIELD_ALIASES[field_key]

    # Strip the field name so "a1c" inside "hba1c" cannot be re-read as a number
    # boundary, and so a bare "18-65" pattern anchors cleanly.
    remainder = lowered.replace(field_key, " ", 1)

    for pattern, op in _NUMERIC_PATTERNS:
        found = pattern.search(remainder)
        if not found:
            continue
        groups = found.groups()
        try:
            if op is NumericOp.BETWEEN:
                low, high = float(groups[0]), float(groups[1])
                if low > high:
                    low, high = high, low
                return NumericRule(
                    field=field, op=op, low=low, high=high, unit=_detect_unit(text, default_unit)
                )
            return NumericRule(
                field=field,
                op=op,
                low=float(groups[0]),
                unit=_detect_unit(text, default_unit),
            )
        except (ValueError, IndexError):
            # A malformed number means we could not understand the criterion.
            # Fall through to None rather than fabricate a threshold.
            return None
    return None


def _detect_unit(text: str, default_unit: str) -> str:
    lowered = text.lower()
    for spelling, canonical in sorted(_KNOWN_UNITS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if spelling in lowered:
            return canonical
    return default_unit
