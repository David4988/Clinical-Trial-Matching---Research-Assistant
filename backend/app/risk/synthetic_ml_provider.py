"""Live risk provider backed by the trained synthetic Isolation Forest.

This is the real ML path. A monitoring window arrives, the provider derives the
patient's six model features from it and the window before it, loads the frozen
artifact, and scores it. No precomputed scenario output is consulted, and the
patient's trajectory label is never read — `SyntheticArtifactProvider` does both
of those things on purpose and remains available for offline demonstration.

    PatientState
      -> PatientWindowState        current + previous window
      -> six-feature vector        explicit order, no fabricated deltas
      -> IsolationForest           loaded once, never refitted
      -> deterministic evidence    from the live observation
      -> deterministic explanation
      -> RiskAssessment            the existing schema, unchanged

The boundary in `provider.py` holds exactly as before: this provider reads state
and returns an opinion. It cannot express an action, cannot reach the trust gate,
and cannot reach the protocol table. A trained model changes what the opinion is
worth, not what it is permitted to do.

Nothing raises out of `assess`. A missing artifact, an unscoreable first window
or an unexpected failure all produce a degraded assessment, which the trust gate
turns into UNKNOWN — never into a reassuring GREEN.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from .provider import RiskProvider
from ..monitoring import ids, protocol
from ..schema.monitoring_enums import DataQualityStatus, RiskLevel
from ..schema.monitoring_result import (
    ContributingFactor,
    PatientState,
    RiskAssessment,
)
from ..synthetic.inference import (
    InferenceResult,
    PatientWindowState,
    SyntheticInferenceEngine,
    build_evidence,
    default_engine,
    explain,
)
from ..synthetic.inference.contract import (
    EXPECTED_MODEL_VERSION,
    MODEL_SIGNALS,
    ModelUnavailable,
)

logger = logging.getLogger("app.risk.synthetic_ml")

#: The estimator's own decision boundary, in the negated-score space this
#: codebase reports. `predict` returns -1 — anomaly — exactly above it. NOT a
#: tunable threshold: it is `contamination=0.10` as sklearn resolved it at fit
#: time, and it is the model, not this file, that decides RED.
ANOMALY_BOUNDARY = 0.0

#: SYNTHETIC. How far below its own boundary a score still earns a second look.
#: Isolation Forest emits one number and no notion of "borderline", so this band
#: is an application presentation choice, chosen from the observed evaluation
#: distribution (scores span roughly -0.144 to +0.227). It can only ever move a
#: window from GREEN to AMBER; it can never create or suppress a RED.
AMBER_MARGIN = 0.02

#: SYNTHETIC. Half-width used to project the model's score onto the [0, 1] range
#: `RiskAssessment.score` requires. 0.5 lands exactly on the decision boundary,
#: so "above 0.5" and "the model flagged it" mean the same thing on screen.
SCORE_SPAN = 0.25

#: How much the provider trusts the vector it was given — a property of the
#: record, not of the answer. An Isolation Forest returns no calibrated
#: probability, so deriving confidence from the anomaly score would be inventing
#: a number the model never produced.
CONFIDENCE_BY_QUALITY = {
    DataQualityStatus.OK: 0.90,
    DataQualityStatus.DEGRADED: 0.60,
    DataQualityStatus.UNTRUSTWORTHY: 0.30,
}

_MEASUREMENT_BY_SIGNAL = {signal: measurement for measurement, signal in MODEL_SIGNALS}

_UNITS = {"heart_rate": "bpm", "spo2": "%", "respiratory_rate": "breaths/min"}

#: An optional prose layer — a Gemini call, or anything else — may be supplied
#: to rephrase a finished assessment. It receives the evidence and the
#: deterministic explanation and returns extra advisory lines. It is handed no
#: mutable state, its output lands only in `likely_patterns`, and the assessment
#: is already complete before it runs, so it cannot influence the score, the
#: level, the evidence, or any physiological value.
Narrator = Callable[[dict[str, Any], dict[str, Any]], list[str]]


class SyntheticMLProvider(RiskProvider):
    """Advisory risk from live Isolation Forest inference."""

    name = "synthetic_ml"
    version = EXPECTED_MODEL_VERSION

    def __init__(
        self,
        engine: SyntheticInferenceEngine | None = None,
        narrator: Narrator | None = None,
    ) -> None:
        self._engine = engine or default_engine()
        self._narrator = narrator

        # Report the artifact's own version rather than the constant, so a
        # cycle is traceable to the file that actually scored it.
        try:
            self.version = self._engine.model_version
            self._feature_version = self._engine.feature_version
        except ModelUnavailable as exc:
            logger.warning("Synthetic ML artifact unavailable at startup: %s", exc)
            self._feature_version = "unknown"

    # -- the provider contract ---------------------------------------------

    def assess(self, state: PatientState, now: datetime) -> RiskAssessment:
        try:
            return self._assess(state, now)
        except ModelUnavailable as exc:
            return self._degraded(state, now, f"Model artifact unavailable: {exc}")
        except Exception as exc:  # noqa: BLE001 - advisory layer must never abort a cycle
            logger.exception("Synthetic ML inference failed", exc_info=exc)
            return self._degraded(
                state, now, f"Live inference failed: {type(exc).__name__}."
            )

    def _assess(self, state: PatientState, now: datetime) -> RiskAssessment:
        window_state = PatientWindowState.from_observations(
            state.patient_id, list(state.recent_observations)
        )

        result = self._engine.score(window_state)
        if not result.scored:
            # No previous window, so three of the six features do not exist.
            # Nothing is invented to stand in for them. This is UNKNOWN but it
            # is *not* `degraded`: the provider is working perfectly and is
            # reporting that the record cannot yet support a verdict, which is
            # a different fact from "the provider fell over".
            return self._unassessable(
                state, now, result.reason or "Window not scoreable."
            )

        evidence = build_evidence(state, window_state, result)
        explanation = explain(evidence)

        score = _display_score(result.anomaly_score)
        level = _level_for(result)

        patterns = [explanation["evidence_summary"]]
        patterns.append(
            f"Model score {result.anomaly_score:+.6f} against its own decision "
            f"boundary of {ANOMALY_BOUNDARY:+.2f} (higher is more unusual)."
        )
        patterns.extend(self._narrate(evidence, explanation))
        patterns.append(
            f"[Source: {self.name} | Model: {result.model_version} | "
            f"Features: {result.feature_version}]"
        )

        return RiskAssessment(
            assessment_id=ids.new_id(ids.RISK),
            patient_id=state.patient_id,
            trial_id=state.trial_id,
            assessed_at=now,
            level=level,
            score=score,
            confidence=CONFIDENCE_BY_QUALITY.get(state.data_quality.status, 0.30),
            prediction_horizon_hours=protocol.PREDICTION_HORIZON_HOURS,
            contributing_factors=_factors(result, explanation),
            likely_patterns=[p for p in patterns if p],
            provider=self.name,
            model_version=result.model_version,
            degraded=False,
        )

    # -- helpers -----------------------------------------------------------

    def _narrate(
        self, evidence: dict[str, Any], explanation: dict[str, Any]
    ) -> list[str]:
        """Run the optional prose layer. Its failure is never the cycle's."""
        if self._narrator is None:
            return []
        try:
            return [line for line in self._narrator(evidence, explanation) if line]
        except Exception as exc:  # noqa: BLE001 - narration is decoration
            logger.warning("Narrator failed; continuing without it: %s", exc)
            return []

    def _unassessable(
        self, state: PatientState, now: datetime, reason: str
    ) -> RiskAssessment:
        """The provider ran and found the record cannot support a verdict."""
        return self._empty(state, now, reason, degraded=False)

    def _degraded(
        self, state: PatientState, now: datetime, reason: str
    ) -> RiskAssessment:
        """The provider itself failed. The gate will say so explicitly."""
        return self._empty(state, now, reason, degraded=True)

    def _empty(
        self, state: PatientState, now: datetime, reason: str, degraded: bool
    ) -> RiskAssessment:
        return RiskAssessment(
            assessment_id=ids.new_id(ids.RISK),
            patient_id=state.patient_id,
            trial_id=state.trial_id,
            assessed_at=now,
            level=RiskLevel.UNKNOWN,
            score=0.0,
            confidence=0.0,
            prediction_horizon_hours=protocol.PREDICTION_HORIZON_HOURS,
            contributing_factors=[],
            likely_patterns=[
                reason,
                f"[Source: {self.name} | Model: {self.version} | "
                f"Features: {self._feature_version}]",
            ],
            provider=self.name,
            model_version=self.version,
            degraded=degraded,
        )


# -- scoring translation ---------------------------------------------------


def _level_for(result: InferenceResult) -> RiskLevel:
    """Band the model's output. RED is the model's call, not this function's."""
    if result.predicted_anomaly == 1:
        return RiskLevel.RED
    if (result.anomaly_score or 0.0) >= ANOMALY_BOUNDARY - AMBER_MARGIN:
        return RiskLevel.AMBER
    return RiskLevel.GREEN


def _display_score(anomaly_score: float | None) -> float:
    """Project the model's score onto [0, 1] with the boundary at 0.5."""
    if anomaly_score is None:
        return 0.0
    projected = 0.5 + anomaly_score / (2.0 * SCORE_SPAN)
    return round(min(max(projected, 0.0), 1.0), 4)


def _factors(
    result: InferenceResult, explanation: dict[str, Any]
) -> list[ContributingFactor]:
    """Explain the score from the features the model actually received."""
    features = result.feature_values

    moved = {
        signal: abs(features[f"{signal}_delta"])
        for _, signal in MODEL_SIGNALS
        if f"{signal}_delta" in features
    }
    # Weights are relative within this window: the largest mover gets 1.0. An
    # absolute scale would need a normalisation constant nothing here provides.
    largest = max(moved.values()) if moved else 0.0

    factors = [
        ContributingFactor(
            factor=_MEASUREMENT_BY_SIGNAL[signal].value,
            detail=(
                f"{features[signal]:g} {_UNITS[signal]} at this window, "
                f"{features[f'{signal}_delta']:+g} since the previous window. "
                "Both entered the model as features."
            ),
            weight=round(moved[signal] / largest, 4) if largest > 0 else 0.0,
            measurement_type=_MEASUREMENT_BY_SIGNAL[signal],
        )
        for _, signal in MODEL_SIGNALS
        if signal in moved
    ]
    factors.sort(key=lambda f: f.weight, reverse=True)

    factors.append(
        ContributingFactor(
            factor="ISOLATION_FOREST",
            detail=(
                f"Trained Isolation Forest {result.model_version} scored this "
                f"window at {result.anomaly_score:+.6f} and classified it as "
                f"{'anomalous' if result.predicted_anomaly else 'normal'} "
                f"({explanation['explanation_type']})."
            ),
            weight=1.0 if result.predicted_anomaly else 0.0,
        )
    )
    return factors


__all__ = ["SyntheticMLProvider", "Narrator"]
