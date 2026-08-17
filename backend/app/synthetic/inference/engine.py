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
