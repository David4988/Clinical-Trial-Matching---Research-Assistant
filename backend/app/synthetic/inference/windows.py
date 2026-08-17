"""Per-patient temporal state, and the six-feature vector derived from it.

The model's features are half deltas, so scoring a window requires knowing the
patient's *previous* window. This module is where that memory lives.

Why it is derived rather than stored
------------------------------------
The obvious implementation is a `dict[patient_id, previous_window]` held in the
provider. It is rejected here on purpose. `PatientState` is recomputed from the
observation store on every read precisely so there is no stored derived state to
fall out of date (see `monitoring/state.py`), and a mutable cache in the risk
layer would undo that: it would not survive a restart, would diverge between
workers, would make a replayed demo produce different numbers the second time,
and would be exactly the kind of cache-invalidation bug the architecture was
shaped to exclude.

So the previous window is *derived* from the observations the caller already
holds. The observation store is the temporal state. Two properties follow for
free rather than by testing:

  * **No cross-patient leakage is possible.** The window sequence is built from
    one patient's observations; there is no shared structure for another
    patient's readings to reach.
  * **The same inputs always produce the same features.** Re-running a cycle
    over the same record recomputes the identical vector.

What counts as a window
-----------------------
A window is one instant at which *all three* model signals were recorded. The
research pipeline emits every signal in every 5-minute window and takes deltas
against `shift(1)`, so "the previous row" and "the previous complete window" are
the same thing there. Here they can differ, and the strict reading is used: the
previous window is the immediately preceding recorded instant, and if a signal
is missing from it there is no delta and the window is not scored. That mirrors
`prepare_model_matrix`'s `dropna`, and it errs toward UNKNOWN, which is the
direction this codebase always errs in.

The first window of a patient has no predecessor. Nothing is fabricated for it —
no zero, no carry-forward, no population default. `features()` returns None and
the caller degrades. This is the same choice `score_observations` makes in the
research repository, where an unscoreable row gets a null score rather than a
reassuring one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contract import DELTA_DECIMALS, FEATURE_ORDER, MODEL_SIGNALS
from ...schema.monitoring import Observation


@dataclass(frozen=True)
class MonitoringWindow:
    """One instant at which every model signal was recorded."""

    patient_id: str
    recorded_at: datetime
    #: Keyed by model signal name — "heart_rate", "spo2", "respiratory_rate".
    values: dict[str, float]

    def value(self, signal: str) -> float:
        return self.values[signal]


@dataclass(frozen=True)
class PatientWindowState:
    """A patient's current window and the one before it.

    This is the whole of the temporal state the model needs. Both fields may be
    None — a patient with no complete window yet, or with only their first.
    """

    patient_id: str
    current: MonitoringWindow | None = None
    previous: MonitoringWindow | None = None

    @property
    def has_delta(self) -> bool:
        return self.current is not None and self.previous is not None

    @classmethod
    def from_observations(
        cls, patient_id: str, observations: list[Observation]
    ) -> PatientWindowState:
        """Derive the last two complete windows from a patient's record."""
        windows = build_windows(patient_id, observations)
        return cls(
            patient_id=patient_id,
            current=windows[-1] if windows else None,
            previous=windows[-2] if len(windows) >= 2 else None,
        )

    def features(self) -> tuple[float, ...] | None:
        """The six-feature vector in `FEATURE_ORDER`, or None if unscoreable.

        Returns a plain tuple of floats. Ordering is taken from the contract
        constant, never from a dict, so it cannot drift.
        """
        if not self.has_delta:
            return None

        current, previous = self.current, self.previous
        values: dict[str, float] = {}
        for _, signal in MODEL_SIGNALS:
            values[signal] = float(current.value(signal))
            values[f"{signal}_delta"] = round(
                float(current.value(signal)) - float(previous.value(signal)),
                DELTA_DECIMALS,
            )

        return tuple(values[name] for name in FEATURE_ORDER)

    def unscoreable_reason(self) -> str | None:
        """Why this patient cannot be scored yet, in plain language."""
        if self.current is None:
            return (
                "No monitoring window has recorded heart rate, SpO2 and "
                "respiratory rate at the same instant."
            )
        if self.previous is None:
            return (
                "Only one complete monitoring window exists. The model's "
                "features include change since the previous window, which has "
                "no value yet. No previous reading was invented to fill it."
            )
        return None


def build_windows(
    patient_id: str, observations: list[Observation]
) -> list[MonitoringWindow]:
    """A patient's complete monitoring windows, oldest first.

    Observations are grouped by exact `recorded_at`, which is how every
    ingestion path in this codebase emits a batch. Where the same signal is
    recorded twice at one instant the later row wins, matching the "the most
    recent reading was used" rule in `monitoring/quality.py`.

    Instants missing any of the three signals are dropped, not filled.
    """
    wanted = {measurement: signal for measurement, signal in MODEL_SIGNALS}

    grouped: dict[datetime, dict[str, float]] = {}
    for observation in sorted(observations, key=lambda o: o.recorded_at):
        if observation.patient_id != patient_id:
            continue
        signal = wanted.get(observation.measurement_type)
        if signal is None:
            continue
        grouped.setdefault(observation.recorded_at, {})[signal] = observation.value

    return [
        MonitoringWindow(
            patient_id=patient_id, recorded_at=recorded_at, values=dict(values)
        )
        for recorded_at, values in sorted(grouped.items())
        if len(values) == len(MODEL_SIGNALS)
    ]
