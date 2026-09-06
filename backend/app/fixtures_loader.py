"""Load canonical fixtures from disk.

Fixtures are plain canonical JSON — the same shape POST /screen accepts. They
exist so the engine can be developed and tested with no PDF in the loop, which
is the practical payoff of having a canonical boundary at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema.clinical import Patient
from .schema.obligations import ResponsibleParty
from .schema.trial import Trial

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _read(name: str) -> dict:
    path = FIXTURES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Fixture '{name}' not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_patient(name: str) -> Patient:
    return Patient.model_validate(_read(name))


def load_trial(name: str) -> Trial:
    return Trial.model_validate(_read(name))


def load_parties() -> list[ResponsibleParty]:
    """The responsible-party registry, seeded on startup — same pattern as
    `load_trial` / `load_patient`, but a list rather than one-name-per-file
    since the registry is small and always loaded in full."""
    path = FIXTURES_DIR / "parties.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ResponsibleParty.model_validate(item) for item in raw]


def available() -> dict[str, list[str]]:
    names = sorted(p.stem for p in FIXTURES_DIR.glob("*.json"))
    return {
        "patients": [n for n in names if n.startswith("patient_")],
        "trials": [n for n in names if n.startswith("trial_")],
    }
