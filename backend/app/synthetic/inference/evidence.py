"""Deterministic evidence and explanation for a live-scored window.

The shape mirrors `synthetic_trial/src/evidence.py` and `explain.py` in the
research repository, so an explanation produced here reads the same as one in a
research report. It is a re-implementation rather than an import, for the same
reason `contract.py` is: the backend does not depend on the research package.

Everything here is a pure function of the *live* observation and the model's
output. Nothing consults `synthetic_demo_cases.json`, and nothing consults the
patient's trajectory label — the explanation is derived from what was measured,
not from what the demo generator intended.

One deliberate divergence from research
---------------------------------------
`synthetic_trial/src/evidence.py` reads a `data_quality_label` column that its
generator never writes (the column is named `data_quality`), so every research
evidence object reports "GOOD" and its explainer can never reach the `data_gap`
branch. That is a research-side reporting bug; it does not touch the six model
features or any score. Rather than reproduce it, the application uses its own
`DataQuality`, which is the authoritative quality signal here and already drives
the trust gate.
"""

from __future__ import annotations

from typing import Any

from .contract import MODEL_SIGNALS
from .engine import InferenceResult
from .windows import PatientWindowState
from ...schema.monitoring_enums import DataQualityStatus
from ...schema.monitoring_result import PatientState

#: Research's relative weighting when naming the single strongest signal: a 2%
#: SpO2 move is treated as comparable to a ~10 bpm heart-rate move. Copied so
#: application and research name the same driver for the same window.
_STRENGTH_WEIGHTS = {"heart_rate": 1.0, "spo2": 5.0, "respiratory_rate": 2.0}

#: Deltas smaller than this are float noise, not a physiological direction.
_DIRECTION_THRESHOLD = 0.1

_QUALITY_LABELS = {
    DataQualityStatus.OK: "GOOD",
    DataQualityStatus.DEGRADED: "PARTIAL",
    DataQualityStatus.UNTRUSTWORTHY: "POOR",
}

_SIGNAL_LABELS = {
    "heart_rate": "hr",
    "spo2": "spo2",
    "respiratory_rate": "rr",
}


def build_evidence(
    state: PatientState,
    window_state: PatientWindowState,
    result: InferenceResult,
) -> dict[str, Any]:
    """Structure what the model was shown, alongside what it returned."""
    features = result.feature_values
    signals: dict[str, Any] = {}
    for _, signal in MODEL_SIGNALS:
        current = window_state.current
        signals[_SIGNAL_LABELS[signal]] = {
            "current_mean": (
                float(current.value(signal)) if current is not None else None
            ),
            "delta": features.get(f"{signal}_delta"),
        }

    evidence: dict[str, Any] = {
        "patient_id": state.patient_id,
        "trial_id": state.trial_id,
        "timestamp": (
            window_state.current.recorded_at.isoformat()
            if window_state.current
            else None
        ),
        "previous_timestamp": (
            window_state.previous.recorded_at.isoformat()
            if window_state.previous
            else None
        ),
        "anomaly_score": result.anomaly_score,
        "predicted_anomaly": result.predicted_anomaly,
        "signals": signals,
        "data_quality": _QUALITY_LABELS.get(state.data_quality.status, "POOR"),
        "data_quality_status": state.data_quality.status.value,
        "observation_count": state.observation_count,
        "model_version": result.model_version,
        "feature_version": result.feature_version,
        "scored": result.scored,
    }

    strengths = {
        signal: abs(features[f"{signal}_delta"]) * weight
        for signal, weight in _STRENGTH_WEIGHTS.items()
        if features.get(f"{signal}_delta") is not None
    }
    evidence["strongest_signal"] = (
        max(strengths, key=strengths.get)
        if strengths and max(strengths.values()) > 0
        else "none"
    )
    return evidence


def explain(evidence: dict[str, Any]) -> dict[str, Any]:
    """Turn evidence into a structured explanation. No model, no randomness.

    The status comes from the model's own `predicted_anomaly`; this layer never
    decides whether a window is anomalous, only how to say so.
    """
    status = "anomaly" if evidence.get("predicted_anomaly") == 1 else "normal"
    if evidence.get("data_quality") != "GOOD":
        status = "data_gap"

    key_signals: list[str] = []
    directions: list[str] = []
    for _, signal in MODEL_SIGNALS:
        delta = evidence["signals"][_SIGNAL_LABELS[signal]]["delta"]
        if delta is None or abs(delta) <= _DIRECTION_THRESHOLD:
            continue
        key_signals.append(signal)
        directions.append(
            f"{signal.upper()} {'increasing' if delta > 0 else 'decreasing'}"
        )

    if status == "data_gap":
        explanation_type = "data_quality_gap"
    elif status == "anomaly":
        explanation_type = (
            "acute_physiological_change" if key_signals else "unexplained_anomaly"
        )
    else:
        explanation_type = (
            "minor_physiological_fluctuation"
            if key_signals
            else "physiological_stability"
        )

    if explanation_type == "data_quality_gap":
        summary = (
            f"Data quality is {evidence.get('data_quality_status', 'unknown')}; "
            "the window was scored but the record cannot support a verdict."
        )
    elif explanation_type == "physiological_stability":
        summary = (
            "Model scored window as normal; physiological signals show stability."
        )
    elif explanation_type == "minor_physiological_fluctuation":
        summary = (
            "Model scored window as normal; minor fluctuations observed in "
            "physiological signals."
        )
    elif explanation_type == "acute_physiological_change":
        summary = (
            "Model flagged window as anomalous. Evidence shows significant "
            f"changes in {', '.join(key_signals)}, most prominently "
            f"{evidence.get('strongest_signal', 'none')}."
        )
    else:
        summary = (
            "Model flagged window, but clear physiological drivers could not be "
            "extracted from the delta features."
        )

    return {
        "status": status,
        "explanation_type": explanation_type,
        "key_signals": key_signals,
        "direction": directions,
        "evidence_summary": summary,
        "anomaly_score": evidence.get("anomaly_score"),
    }
