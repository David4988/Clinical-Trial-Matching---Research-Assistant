"""MonitoringService — the single Phase 2 orchestration point.

The direct analogue of `ScreeningService.screen()`, and the order is just as
deliberate:

    state -> risk -> TRUST GATE -> transition -> protocol -> next dose -> persist

Read that ordering as a set of guarantees:

  * The deterministic state is built before any model sees it.
  * The model returns an opinion and is then *filtered* by the gate, which it
    cannot reach or influence.
  * Protocol actions read the gated level, never the raw one.
  * Every step's inputs and reasons are persisted together in one
    `MonitoringCycleResult`, so a decision can never be separated from what
    produced it.

`now` is threaded through explicitly rather than read from the clock, so a
cycle is reproducible and a demo can be replayed exactly.
"""

from __future__ import annotations

from datetime import datetime

from . import ids, protocol
from .gate import apply_trust_gate, detect_transition
from .interventions import build_interventions
from .next_dose import assess_next_dose
from .notifications import (
    InAppNotificationProvider,
    NotificationDeliveryProvider,
    build_notifications,
)
from .state import build_patient_state
from ..repository.monitoring_base import MonitoringRepository
from ..risk.mock_provider import MockRiskProvider
from ..risk.provider import RiskProvider
from ..schema.monitoring import TreatmentAssignment
from ..schema.monitoring_enums import (
    MonitoringEventType,
    RiskLevel,
    TreatmentStatus,
)
from ..schema.monitoring_result import (
    MonitoringCycleResult,
    MonitoringEvent,
    PatientState,
)


class MonitoringService:
    def __init__(
        self,
        monitoring_repository: MonitoringRepository,
        risk_provider: RiskProvider | None = None,
        notification_provider: NotificationDeliveryProvider | None = None,
    ) -> None:
        self.monitoring_repository = monitoring_repository
        self.risk_provider = risk_provider or MockRiskProvider()
        self.notification_provider = notification_provider or InAppNotificationProvider()

    # -- the cycle ---------------------------------------------------------

    def run_cycle(
        self, patient_id: str, trial_id: str, now: datetime, persist: bool = True
    ) -> MonitoringCycleResult:
        repo = self.monitoring_repository

        treatment = self._active_treatment(patient_id, trial_id)
        observations = repo.list_observations(patient_id, trial_id=trial_id)
        adverse_events = repo.list_adverse_events(patient_id)

        # 1. Deterministic state — no model has seen anything yet.
        state = build_patient_state(
            patient_id=patient_id,
            trial_id=trial_id,
            observations=observations,
            now=now,
            treatment=treatment,
            adverse_events=adverse_events,
        )

        # 2. Advisory risk. Reads state, returns an opinion, writes nothing.
        risk = self.risk_provider.assess(state, now)

        # 3. The trust gate. Deterministic, and the provider cannot reach it.
        effective = apply_trust_gate(state, risk)

        # 4. Transition against the previous cycle's applied level.
        previous = repo.latest_cycle(patient_id)
        transition = detect_transition(
            previous.effective_risk.level if previous else None,
            effective,
            patient_id,
            trial_id,
            now,
        )

        # 5. Protocol response, driven by the gated level.
        interventions = build_interventions(state, effective, risk, now)

        # 6. Notifications: generated here, delivered by a separate provider.
        notifications = [
            self.notification_provider.deliver(notification, now)
            for notification in build_notifications(
                state, effective, interventions, now
            )
        ]

        # 7. Dose readiness — decision support only.
        next_dose = assess_next_dose(state, effective, treatment, now)

        cycle = MonitoringCycleResult(
            cycle_id=ids.new_id(ids.CYCLE),
            patient_id=patient_id,
            trial_id=trial_id,
            generated_at=now,
            state=state,
            risk=risk,
            effective_risk=effective,
            transition=transition,
            interventions=interventions,
            notifications=notifications,
            next_dose=next_dose,
            summary=_summarise(effective, next_dose, state),
        )

        if persist:
            repo.save_cycle(cycle)
            if notifications:
                repo.save_notifications(notifications)
            repo.append_events(_events(cycle, now))

        return cycle

    # -- reads -------------------------------------------------------------

    def latest_cycle(self, patient_id: str) -> MonitoringCycleResult | None:
        return self.monitoring_repository.latest_cycle(patient_id)

    def timeline(self, patient_id: str) -> list[MonitoringEvent]:
        return self.monitoring_repository.list_events(patient_id)

    def trial_overview(self, trial_id: str) -> dict:
        """Aggregate for the Trial Overview screen.

        Counts are derived from each patient's most recent cycle, so the board
        reflects current state rather than a running total of past alarms.
        """
        treatments = self.monitoring_repository.list_treatments(trial_id=trial_id)
        counts = {level.value: 0 for level in RiskLevel}
        attention: list[dict] = []
        patients: list[dict] = []

        for treatment in treatments:
            cycle = self.monitoring_repository.latest_cycle(treatment.patient_id)
            level = cycle.effective_risk.level if cycle else RiskLevel.UNKNOWN
            counts[level.value] += 1

            entry = {
                "patient_id": treatment.patient_id,
                "treatment_id": treatment.treatment_id,
                "drug_name": treatment.drug_name,
                "treatment_status": treatment.status.value,
                "dose_count": treatment.dose_count,
                "risk_level": level.value,
                "risk_score": cycle.risk.score if cycle else None,
                "gated": cycle.effective_risk.gated if cycle else False,
                "next_dose": (
                    cycle.next_dose.decision.value if cycle and cycle.next_dose else None
                ),
                "last_assessed_at": cycle.generated_at.isoformat() if cycle else None,
                "data_quality": (
                    cycle.state.data_quality.status.value if cycle else None
                ),
            }
            patients.append(entry)
            if level in (RiskLevel.RED, RiskLevel.AMBER, RiskLevel.UNKNOWN):
                attention.append(entry)

        attention.sort(key=lambda e: _ATTENTION_ORDER.get(e["risk_level"], 9))

        return {
            "trial_id": trial_id,
            "protocol_id": protocol.PROTOCOL_ID,
            "protocol_label": protocol.PROTOCOL_LABEL,
            "total_patients": len(treatments),
            "active_treatments": sum(
                1 for t in treatments if t.status is TreatmentStatus.ACTIVE
            ),
            "risk_counts": counts,
            "requiring_attention": attention,
            "patients": patients,
        }

    # -- helpers -----------------------------------------------------------

    def _active_treatment(
        self, patient_id: str, trial_id: str
    ) -> TreatmentAssignment | None:
        treatments = self.monitoring_repository.list_treatments(
            trial_id=trial_id, patient_id=patient_id
        )
        active = [t for t in treatments if t.status is TreatmentStatus.ACTIVE]
        return active[-1] if active else (treatments[-1] if treatments else None)


_ATTENTION_ORDER = {"RED": 0, "UNKNOWN": 1, "AMBER": 2}


def _summarise(effective, next_dose, state: PatientState) -> str:
    parts = [
        f"Risk {effective.level.value}"
        + (f" (model said {effective.provider_level.value})" if effective.gated else "")
        + "."
    ]
    if next_dose is not None:
        parts.append(f"Next dose: {next_dose.decision.value}.")
    parts.append(f"Data quality {state.data_quality.status.value}.")
    return " ".join(parts)


def _events(cycle: MonitoringCycleResult, now: datetime) -> list[MonitoringEvent]:
    """Timeline entries for one cycle, in the order they logically occurred."""

    def event(event_type, summary, ref_id=None, payload=None) -> MonitoringEvent:
        return MonitoringEvent(
            event_id=ids.new_id(ids.EVENT),
            patient_id=cycle.patient_id,
            trial_id=cycle.trial_id,
            occurred_at=now,
            event_type=event_type,
            summary=summary,
            ref_id=ref_id,
            payload=payload or {},
        )

    events = [
        event(
            MonitoringEventType.RISK_ASSESSED,
            f"{cycle.risk.provider} assessed {cycle.risk.level.value} "
            f"(score {cycle.risk.score:.2f}, confidence {cycle.risk.confidence:.2f}).",
            cycle.risk.assessment_id,
            {
                "level": cycle.risk.level.value,
                "score": cycle.risk.score,
                "factors": [f.factor for f in cycle.risk.contributing_factors],
            },
        )
    ]

    if cycle.effective_risk.gated:
        events.append(
            event(
                MonitoringEventType.DATA_QUALITY_GATE_APPLIED,
                f"Gate applied: {cycle.effective_risk.provider_level.value} -> "
                f"{cycle.effective_risk.level.value}. {cycle.effective_risk.reason}",
                payload={
                    "provider_level": cycle.effective_risk.provider_level.value,
                    "applied_level": cycle.effective_risk.level.value,
                },
            )
        )

    if cycle.transition is not None:
        events.append(
            event(
                MonitoringEventType.RISK_TRANSITION,
                cycle.transition.trigger,
                payload={
                    "from": cycle.transition.from_level.value
                    if cycle.transition.from_level
                    else None,
                    "to": cycle.transition.to_level.value,
                },
            )
        )

    for intervention in cycle.interventions:
        events.append(
            event(
                MonitoringEventType.INTERVENTION_RAISED,
                f"{intervention.action.value.replace('_', ' ').title()} "
                f"({intervention.protocol_rule_id}).",
                intervention.intervention_id,
                {
                    "action": intervention.action.value,
                    "rule": intervention.protocol_rule_id,
                    "interval_minutes": intervention.monitoring_interval_minutes,
                },
            )
        )

    for notification in cycle.notifications:
        events.append(
            event(
                MonitoringEventType.NOTIFICATION_CREATED,
                f"Notified {notification.audience.value.lower()}: {notification.subject}",
                notification.notification_id,
                {
                    "audience": notification.audience.value,
                    "channel": notification.channel.value,
                    "delivered": notification.is_delivered,
                },
            )
        )

    if cycle.next_dose is not None:
        events.append(
            event(
                MonitoringEventType.NEXT_DOSE_ASSESSED,
                f"Next dose: {cycle.next_dose.decision.value}."
                + (
                    f" Blocked by {', '.join(cycle.next_dose.blocking_criteria)}."
                    if cycle.next_dose.blocking_criteria
                    else ""
                ),
                cycle.next_dose.assessment_id,
                {
                    "decision": cycle.next_dose.decision.value,
                    "blocking": cycle.next_dose.blocking_criteria,
                },
            )
        )

    return events
