"""Risk provider abstraction — the ML replacement seam.

Note the signature: `assess` receives a `PatientState` as *input* and returns a
`RiskAssessment` as *output*. It is handed no mutable reference to anything, and
`RiskAssessment` has no field capable of holding a clinical action. So no
provider — the deterministic mock today, a trained model tomorrow — can order an
intervention, hold a dose, or change a treatment.

This is the same technique `ai/provider.py` uses in Phase 1, applied to the
layer that Phase 2 will eventually hand to a real model.

What a provider MAY do: read state, weigh measurements, project a trajectory,
and explain itself through `contributing_factors`.

What a provider MAY NOT do: decide what happens next. The deterministic protocol
layer owns that, and it reads risk as one input among several.

A provider must never raise. If it cannot assess, it returns a degraded
assessment and the monitoring cycle continues on deterministic ground.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..schema.monitoring_result import PatientState, RiskAssessment


class RiskProvider(ABC):
    """Advisory risk estimation over a deterministic patient state."""

    name: str = "abstract"
    version: str = "0"

    @abstractmethod
    def assess(self, state: PatientState, now: datetime) -> RiskAssessment:
        """Return an advisory risk assessment. Must never raise; degrade instead."""
        raise NotImplementedError
