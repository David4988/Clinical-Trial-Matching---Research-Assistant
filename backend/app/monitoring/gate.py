"""The data-quality trust gate.

Phase 1's safety property is that deterministic rules are authoritative and the
AI layer is advisory. Phase 2 inverts the trust model — the risk provider is the
*primary* signal driving clinical action — so it needs an explicit counterweight.

This is it. Before any protocol action is chosen, a deterministic check asks
whether the underlying record can support a verdict at all. If it cannot, the
effective level becomes UNKNOWN no matter what the provider returned.

A model cannot make a patient look safe on the strength of data we already know
is untrustworthy.

Both levels are kept. `EffectiveRisk` carries the provider's raw opinion beside
the applied level and the reason for the difference, rather than overwriting it
— the same instinct that makes Phase 1 surface a `Disagreement` instead of
quietly resolving one. A reviewer can always see what the model thought and why
it was not applied.
"""

from __future__ import annotations

from ..schema.monitoring_enums import RiskLevel
from ..schema.monitoring_result import (
    EffectiveRisk,
    PatientState,
    RiskAssessment,
    RiskTransition,
)


def apply_trust_gate(state: PatientState, risk: RiskAssessment) -> EffectiveRisk:
    """Decide which risk level the protocol layer is allowed to act on."""
    quality = state.data_quality

    if not quality.is_trustworthy:
        blockers = "; ".join(f.message for f in quality.flags) or "record is unusable"
        return EffectiveRisk(
            level=RiskLevel.UNKNOWN,
            provider_level=risk.level,
            gated=True,
            reason=(
                f"Data quality is {quality.status.value}, so no risk verdict was "
                f"applied. {blockers}"
            ),
        )

    if risk.degraded:
        return EffectiveRisk(
            level=RiskLevel.UNKNOWN,
            provider_level=risk.level,
            gated=True,
            reason=(
                f"The risk provider '{risk.provider}' was unavailable, so its "
                "verdict was not applied."
            ),
        )

    return EffectiveRisk(
        level=risk.level,
        provider_level=risk.level,
        gated=False,
        reason=(
            f"Data quality is {quality.status.value}; the provider verdict was "
            "applied unchanged."
        ),
    )


def detect_transition(
    previous_level: RiskLevel | None,
    effective: EffectiveRisk,
    patient_id: str,
    trial_id: str,
    occurred_at,
) -> RiskTransition | None:
    """A transition exists only when the effective level actually changed.

    The first assessment counts as a transition (from None), so the timeline
    records where a patient started.
    """
    if previous_level is effective.level:
        return None

    if previous_level is None:
        trigger = f"First assessment: {effective.level.value}."
    else:
        direction = "escalated" if _rank(effective.level) > _rank(previous_level) else "de-escalated"
        trigger = (
            f"{direction.capitalize()} from {previous_level.value} to "
            f"{effective.level.value}."
        )
        if effective.gated:
            trigger += " Applied by the data-quality gate."

    return RiskTransition(
        patient_id=patient_id,
        trial_id=trial_id,
        from_level=previous_level,
        to_level=effective.level,
        occurred_at=occurred_at,
        trigger=trigger,
    )


#: Ordering for "did this escalate or settle?". UNKNOWN sits above AMBER
#: deliberately: not knowing is more concerning than a known mild excursion.
_ORDER = {
    RiskLevel.GREEN: 0,
    RiskLevel.AMBER: 1,
    RiskLevel.UNKNOWN: 2,
    RiskLevel.RED: 3,
}


def _rank(level: RiskLevel) -> int:
    return _ORDER[level]
