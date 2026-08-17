"""Choosing which risk provider a deployment runs.

There are three, and which one is in play is a *deployment* decision rather than
a request-time one, so it is made once at startup and recorded in the provenance
of every assessment the cycle produces.

    mock          MockRiskProvider          deterministic bands, no ML at all
    synthetic     SyntheticArtifactProvider precomputed research fixtures
    synthetic_ml  SyntheticMLProvider       live Isolation Forest inference

`synthetic` and `synthetic_ml` are not interchangeable and are deliberately not
spelled similarly by accident: the first replays three known cases from a JSON
file and is for offline demonstration and UI work; the second loads the trained
artifact and scores the window that just arrived. `RiskAssessment.provider`
carries whichever one answered, so a stored cycle always says which it was.
"""

from __future__ import annotations

import logging
import os

from .mock_provider import MockRiskProvider
from .provider import RiskProvider

logger = logging.getLogger("app.risk.factory")

MOCK = "mock"
SYNTHETIC = "synthetic"
SYNTHETIC_ML = "synthetic_ml"

PROVIDER_NAMES = (MOCK, SYNTHETIC, SYNTHETIC_ML)

#: Read at application startup. `mock` stays the default so the app still runs
#: with nothing installed beyond `requirements.txt`.
ENV_VAR = "RISK_PROVIDER"


def build_risk_provider(name: str | None = None) -> RiskProvider:
    """Construct the named provider, falling back to the mock if it cannot load.

    Never raises. A deployment that asks for live ML and does not get it is told
    so in the log and continues on the deterministic mock, because a monitoring
    service that will not start is worse than one running a weaker provider.
    """
    chosen = (name or os.environ.get(ENV_VAR) or MOCK).strip().lower()

    if chosen == MOCK:
        return MockRiskProvider()

    if chosen == SYNTHETIC:
        from .synthetic_provider import SyntheticArtifactProvider

        return SyntheticArtifactProvider()

    if chosen == SYNTHETIC_ML:
        try:
            from .synthetic_ml_provider import SyntheticMLProvider

            provider = SyntheticMLProvider()
            # Touch the artifact now rather than discovering at the first cycle
            # that scikit-learn is missing.
            provider._engine.metadata  # noqa: SLF001 - deliberate startup probe
            return provider
        except Exception as exc:  # noqa: BLE001 - startup must not fail here
            logger.error(
                "Could not start the live ML risk provider (%s); falling back "
                "to the deterministic mock.",
                exc,
            )
            return MockRiskProvider()

    logger.warning(
        "Unknown %s=%r; expected one of %s. Using the deterministic mock.",
        ENV_VAR,
        chosen,
        ", ".join(PROVIDER_NAMES),
    )
    return MockRiskProvider()
