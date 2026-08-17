"""Live inference over incoming monitoring windows.

    observations -> PatientWindowState -> features -> Isolation Forest -> evidence

Deliberately small and self-contained: it loads one frozen artifact and scores
one window. It is not a serving platform, holds no queue, spawns no worker, and
never trains.
"""

from .contract import FEATURE_ORDER, MODEL_SIGNALS, ModelUnavailable
from .engine import InferenceResult, SyntheticInferenceEngine, default_engine
from .evidence import build_evidence, explain
from .windows import MonitoringWindow, PatientWindowState, build_windows

__all__ = [
    "FEATURE_ORDER",
    "MODEL_SIGNALS",
    "ModelUnavailable",
    "InferenceResult",
    "SyntheticInferenceEngine",
    "default_engine",
    "build_evidence",
    "explain",
    "MonitoringWindow",
    "PatientWindowState",
    "build_windows",
]
