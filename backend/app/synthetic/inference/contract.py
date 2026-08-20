"""The model deployment contract, restated on the application side.

The research repository owns training. This file owns the application's half of
the agreement, and it is deliberately a *duplicate declaration* rather than an
import: the backend must not depend on the research package, and a contract that
only exists in one place cannot be checked.

`engine.py` loads the artifact's metadata JSON and asserts that what the model
was fitted on equals `FEATURE_ORDER` below. If the research repository ever
reorders, renames, adds or removes a feature, the application refuses to score
rather than silently feeding the estimator a permuted vector — which would not
raise, and would produce confident nonsense.

Regenerate the artifact with, in the research repository:

    .venv/bin/python train_model_artifact.py
"""

from __future__ import annotations

from ...schema.monitoring_enums import MeasurementType

#: The exact vector the Isolation Forest was fitted on, in order. A tuple, so it
#: cannot be mutated and cannot be confused with a dict's iteration order.
FEATURE_ORDER: tuple[str, ...] = (
    "heart_rate",
    "spo2",
    "respiratory_rate",
    "heart_rate_delta",
    "spo2_delta",
    "respiratory_rate_delta",
)

#: The three signals whose current values and deltas make up the six features.
#: Ordered to match the first three entries of FEATURE_ORDER.
MODEL_SIGNALS: tuple[tuple[MeasurementType, str], ...] = (
    (MeasurementType.HEART_RATE, "heart_rate"),
    (MeasurementType.SPO2, "spo2"),
    (MeasurementType.RESPIRATORY_RATE, "respiratory_rate"),
)

#: The artifact this application build expects. Loading a different version is
#: allowed but reported, so a stale artifact is visible rather than silent.
EXPECTED_MODEL_VERSION = "synthetic_if_v1"
EXPECTED_FEATURE_VERSION = "synthetic_features_v1"

#: Research rounds each delta to 4 decimals before fitting. Matching that here
#: is not cosmetic: it is what makes application feature vectors bit-identical
#: to the ones the reported metrics were computed from.
DELTA_DECIMALS = 4
SCORE_DECIMALS = 6


class ModelUnavailable(RuntimeError):
    """The artifact is missing, unreadable, or disagrees with this contract.

    Raised only inside the engine. The risk provider catches it and degrades —
    a monitoring cycle must never abort because a model failed to load.
    """


from datetime import datetime
from typing import Literal
from pydantic import BaseModel

class FeatureEvidence(BaseModel):
    feature_name: str
    raw_value: float | None
    transformed_value: float
    model_weight: float
    contribution: float
    direction: Literal["POSITIVE", "NEGATIVE"]
    objective_description: str

class PredictiveRiskAssessment(BaseModel):
    provider: str
    model_version: str
    feature_version: str
    horizon_hours: int
    score: float | None
    threshold: float
    predicted_deterioration: bool | None
    data_quality_state: str
    evidence: list[FeatureEvidence]
    evaluated_at: datetime
    artifact_checksum: str
