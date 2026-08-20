"""Live Isolation Forest inference over an incoming monitoring window.

Loads the frozen artifact once, validates it against `contract.py`, and scores
one patient's current window. It does not fit, refit, warm-start, or mutate a
single estimator parameter — `sklearn`'s `IsolationForest` is used strictly
through `decision_function` and `predict`, both of which are pure reads.

The scoring convention is copied from the research repository verbatim, because
a sign flip here would invert every verdict downstream and would not raise:

    anomaly_score     = round(-model.decision_function(X), 6)   higher = worse
    predicted_anomaly = 1 when model.predict(X) == -1

Determinism: a fitted Isolation Forest holds fixed trees, so scoring draws no
randomness. The same feature vector returns the same score on every call and in
every process.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .contract import (
    EXPECTED_FEATURE_VERSION,
    EXPECTED_MODEL_VERSION,
    FEATURE_ORDER,
    SCORE_DECIMALS,
    ModelUnavailable,
)
from .windows import PatientWindowState

logger = logging.getLogger("app.synthetic.inference")

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "synthetic_isolation_forest.joblib"
METADATA_PATH = ARTIFACT_DIR / "synthetic_isolation_forest.json"


@dataclass(frozen=True)
class InferenceResult:
    """What the model said about one window, and what it was shown.

    `feature_values` carries the exact vector that entered the estimator, in
    `FEATURE_ORDER`, so a reviewer can reproduce the score by hand. No sklearn
    object appears on this type — nothing from the estimator escapes the engine.
    """

    patient_id: str
    timestamp: datetime | None
    scored: bool
    anomaly_score: float | None = None
    predicted_anomaly: int | None = None
    feature_values: dict[str, float] = field(default_factory=dict)
    model_version: str = EXPECTED_MODEL_VERSION
    feature_version: str = EXPECTED_FEATURE_VERSION
    #: Populated only when `scored` is False.
    reason: str | None = None


class SyntheticInferenceEngine:
    """Loads the frozen artifact once and scores windows against it."""

    def __init__(self, artifact_dir: Path | None = None) -> None:
        self._dir = Path(artifact_dir) if artifact_dir else ARTIFACT_DIR
        self._model: Any | None = None
        self._metadata: dict[str, Any] | None = None
        self._lock = threading.Lock()

    # -- loading -----------------------------------------------------------

    @property
    def metadata(self) -> dict[str, Any]:
        self._ensure_loaded()
        assert self._metadata is not None
        return self._metadata

    @property
    def model_version(self) -> str:
        return str(self.metadata["model_version"])

    @property
    def feature_version(self) -> str:
        return str(self.metadata.get("feature_version", EXPECTED_FEATURE_VERSION))

    def _ensure_loaded(self) -> None:
        """Load and validate on first use. Idempotent and thread-safe."""
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return

            model_path = self._dir / MODEL_PATH.name
            metadata_path = self._dir / METADATA_PATH.name

            if not model_path.exists() or not metadata_path.exists():
                raise ModelUnavailable(
                    f"Model artifact incomplete: expected {model_path.name} and "
                    f"{metadata_path.name} in {self._dir}. Regenerate it in the "
                    "research repository with `python train_model_artifact.py` "
                    "and copy the pair across."
                )

            try:
                with open(metadata_path) as handle:
                    metadata = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                raise ModelUnavailable(f"Unreadable model metadata: {exc}") from exc

            self._validate(metadata, model_path)

            # Unpickling executes code, so this is confined to a first-party
            # build product that ships in this repository and whose SHA-256 has
            # just been checked against the metadata above. Never point this
            # engine at an artifact from anywhere else.
            try:
                import joblib
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise ModelUnavailable(
                    "scikit-learn/joblib are not installed, so live ML "
                    "inference is unavailable."
                ) from exc

            try:
                model = joblib.load(model_path)
            except Exception as exc:  # noqa: BLE001 - any failure means degrade
                raise ModelUnavailable(f"Could not deserialise the model: {exc}") from exc

            if not (hasattr(model, "decision_function") and hasattr(model, "predict")):
                raise ModelUnavailable(
                    "The deserialised object is not a scoreable estimator."
                )

            self._metadata = metadata
            self._model = model
            logger.info(
                "Loaded synthetic ML artifact %s (features %s, fitted on %s rows)",
                metadata["model_version"],
                metadata.get("feature_version"),
                metadata.get("training_matrix", {}).get("rows"),
            )

    def _validate(self, metadata: dict[str, Any], model_path: Path) -> None:
        """Refuse an artifact that disagrees with this build's contract."""
        names = tuple(metadata.get("features", {}).get("names", ()))
        if names != FEATURE_ORDER:
            raise ModelUnavailable(
                f"Artifact feature order {names} does not match this "
                f"application's {FEATURE_ORDER}. Scoring a permuted vector "
                "would not raise and would produce confident nonsense, so the "
                "model is not loaded."
            )

        expected_sha = metadata.get("model_sha256")
        if expected_sha:
            digest = hashlib.sha256()
            with open(model_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected_sha:
                raise ModelUnavailable(
                    f"{model_path.name} does not match the checksum its "
                    "metadata records. The artifact pair is inconsistent."
                )

        # A version drift is worth knowing about but is not a reason to refuse:
        # the feature contract above is what actually makes scoring safe.
        if metadata.get("model_version") != EXPECTED_MODEL_VERSION:
            logger.warning(
                "Artifact model_version %s differs from the expected %s.",
                metadata.get("model_version"),
                EXPECTED_MODEL_VERSION,
            )
        if metadata.get("feature_version") != EXPECTED_FEATURE_VERSION:
            logger.warning(
                "Artifact feature_version %s differs from the expected %s.",
                metadata.get("feature_version"),
                EXPECTED_FEATURE_VERSION,
            )

    # -- inference ---------------------------------------------------------

    def score(self, state: PatientWindowState) -> InferenceResult:
        """Score one patient's current window against their previous one."""
        features = state.features()
        if features is None:
            return InferenceResult(
                patient_id=state.patient_id,
                timestamp=state.current.recorded_at if state.current else None,
                scored=False,
                reason=state.unscoreable_reason(),
            )

        self._ensure_loaded()
        assert self._model is not None

        # A single row. `decision_function` wants 2-D, and building the list
        # from FEATURE_ORDER keeps the column order explicit at the last step
        # before it reaches the estimator.
        matrix = [list(features)]
        decision = float(self._model.decision_function(matrix)[0])
        predicted = int(self._model.predict(matrix)[0] == -1)

        return InferenceResult(
            patient_id=state.patient_id,
            timestamp=state.current.recorded_at if state.current else None,
            scored=True,
            anomaly_score=round(-decision, SCORE_DECIMALS),
            predicted_anomaly=predicted,
            feature_values=dict(zip(FEATURE_ORDER, features)),
            model_version=self.model_version,
            feature_version=self.feature_version,
        )


#: One engine per process. The artifact is ~1 MB and immutable once fitted, so
#: there is no reason to deserialise it per request — and no risk in sharing it,
#: since scoring only reads.
_default_engine: SyntheticInferenceEngine | None = None
_default_lock = threading.Lock()


def default_engine() -> SyntheticInferenceEngine:
    global _default_engine
    if _default_engine is None:
        with _default_lock:
            if _default_engine is None:
                _default_engine = SyntheticInferenceEngine()
    return _default_engine

import numpy as np
import pandas as pd
import hashlib
from typing import Any
import sys
import os

# We assume the research package is accessible in production environment 
# via an internal module path, but for the patch we append it to sys.path.
import sys
import os
RESEARCH_DIR = os.path.expanduser("~/Projects/trialguard-earlywarning")
if RESEARCH_DIR not in sys.path:
    sys.path.append(RESEARCH_DIR)

from src.features_v2 import build_feature_matrix
from .contract import FeatureEvidence, PredictiveRiskAssessment

class EarlywarningInferenceEngine:
    def __init__(self, artifact_dir: Path | None = None) -> None:
        self._dir = Path(artifact_dir) if artifact_dir else ARTIFACT_DIR
        self._model: Any | None = None
        self._metadata: dict[str, Any] | None = None
        self._lock = threading.Lock()

    @property
    def metadata(self) -> dict[str, Any]:
        self._ensure_loaded()
        return self._metadata

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        with self._lock:
            if self._model is not None:
                return

            model_path = self._dir / "earlywarning_v2.joblib"
            metadata_path = self._dir / "earlywarning_v2.json"

            if not model_path.exists() or not metadata_path.exists():
                raise ModelUnavailable("Model artifact incomplete")

            try:
                with open(metadata_path) as handle:
                    metadata = json.load(handle)
            except Exception as exc:
                raise ModelUnavailable(f"Unreadable model metadata: {exc}") from exc

            self._validate(metadata, model_path)

            try:
                import joblib
                model = joblib.load(model_path)
            except Exception as exc:
                raise ModelUnavailable(f"Could not deserialise the model: {exc}") from exc

            self._metadata = metadata
            self._model = model

    def _validate(self, metadata: dict[str, Any], model_path: Path) -> None:
        expected_sha = metadata.get("model_sha256")
        if not expected_sha:
            raise ModelUnavailable("No SHA256 in metadata")

        digest = hashlib.sha256()
        with open(model_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha:
            raise ModelUnavailable("Model SHA256 mismatch")
            
        if metadata.get("model_version") != "v2":
            raise ModelUnavailable("Wrong model version")
        if metadata.get("feature_version") != "v2":
            raise ModelUnavailable("Wrong feature version")
        if metadata.get("threshold") != 0.733:
            raise ModelUnavailable("Wrong threshold")

    def score_earlywarning(self, state: PatientWindowState, observations: list[Any], now: datetime) -> PredictiveRiskAssessment:
        self._ensure_loaded()
        metadata_threshold = self.metadata.get("threshold", 0.733)
        checksum = self.metadata.get("model_sha256", "")

        def empty_assessment(reason: str) -> PredictiveRiskAssessment:
            return PredictiveRiskAssessment(
                provider="Earlywarning-v2",
                model_version="v2",
                feature_version="v2",
                horizon_hours=3,
                score=None,
                threshold=metadata_threshold,
                predicted_deterioration=None,
                data_quality_state=reason,
                evidence=[],
                evaluated_at=now,
                artifact_checksum=checksum
            )

        if state.current is None:
            return empty_assessment("INSUFFICIENT_DATA")

        # Explicit 180 minute boundary
        import datetime as dt
        cutoff = now - dt.timedelta(minutes=180)
        recent_obs = [o for o in observations if cutoff <= o.recorded_at <= now]

        obs_dicts = []
        for o in recent_obs:
            obs_dicts.append({
                "patient_id": o.patient_id,
                "recorded_at": o.recorded_at.replace(microsecond=0),
                "measurement_type": getattr(o.measurement_type, "value", o.measurement_type),
                "value": o.value
            })
            
        obs_df = pd.DataFrame(obs_dicts)
        t = state.current.recorded_at
        grid_df = pd.DataFrame([{"patient_id": state.patient_id, "t": t.replace(microsecond=0)}])
        matrix = build_feature_matrix(obs_df, grid_df)
        
        if "time__minutes_since_first_obs" in matrix.columns:
            matrix = matrix.drop(columns=["time__minutes_since_first_obs"])
            
        is_sufficient = True
        if len(obs_df) < 3:
            is_sufficient = False
        
        if is_sufficient:
            stale_60m_count = 0
            for v in ["HEART_RATE", "SPO2", "RESPIRATORY_RATE", "SYSTOLIC_BP", "DIASTOLIC_BP"]:
                stale = matrix[f"{v}__staleness_min"].iloc[0]
                if np.isnan(stale) or stale > 180.0:
                    is_sufficient = False
                    break
                if stale > 60.0:
                    stale_60m_count += 1
            if stale_60m_count > 2:
                is_sufficient = False
                
        if not is_sufficient:
            return empty_assessment("INSUFFICIENT_DATA")
            
        # Verify columns match
        if list(matrix.columns) != self.metadata["feature_columns"]:
             raise ModelUnavailable("Feature columns mismatch")
             
        # Extract evidence math
        imputer = self._model.named_steps["imputer"]
        scaler = self._model.named_steps["scaler"]
        clf = self._model.named_steps["clf"]
        
        X_imp = imputer.transform(matrix)
        X_scaled = scaler.transform(X_imp)
        contribs = X_scaled[0] * clf.coef_[0]
        
        decision = np.sum(contribs) + clf.intercept_[0]
        risk_score = float(self._model.predict_proba(matrix)[0, 1])
        
        evidence = []
        for i, c in enumerate(contribs):
            direction = "POSITIVE" if c > 0 else "NEGATIVE"
            evidence.append(FeatureEvidence(
                feature_name=matrix.columns[i],
                raw_value=float(matrix.iloc[0, i]),
                transformed_value=float(X_scaled[0, i]),
                model_weight=float(clf.coef_[0, i]),
                contribution=float(c),
                direction=direction,
                objective_description=f"Contribution: {c:.3f}"
            ))
            
        evidence.sort(key=lambda x: abs(x.contribution), reverse=True)
        top_evidence = evidence[:10]
        
        return PredictiveRiskAssessment(
            provider="Earlywarning-v2",
            model_version="v2",
            feature_version="v2",
            horizon_hours=3,
            score=risk_score,
            predicted_deterioration=risk_score >= metadata_threshold,
            threshold=metadata_threshold,
            data_quality_state="OK",
            evidence=top_evidence,
            evaluated_at=now,
            artifact_checksum=checksum
        )

# Inject into engine.py
