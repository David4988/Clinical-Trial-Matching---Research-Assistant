"""Notifications: generation and delivery, deliberately kept apart.

`build_notifications` decides *what should be said to whom*. A
`NotificationDeliveryProvider` decides *how it physically leaves the building*.
Nothing in this module sends anything.

That split is the whole point. Adding real email, SMS or push later means
writing one new provider class; the rules about who gets told what do not move,
and cannot accidentally acquire a dependency on a mail server.

One rule carried over from `docs/PHASES.md`: **patient-facing messages are not
generated automatically from a risk level.** Phase 6 reserves that for a
researcher-approved `ApprovalRecord`. Here, clinicians and investigators are
notified; the patient is not messaged by the algorithm.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from . import ids, protocol
from ..schema.monitoring_enums import (
    InterventionAction,
    NotificationAudience,
    NotificationChannel,
    RiskLevel,
)
from ..schema.monitoring_result import (
    EffectiveRisk,
    Intervention,
    Notification,
    PatientState,
)

_SUBJECTS: dict[RiskLevel, str] = {
    RiskLevel.GREEN: "Routine monitoring continues",
    RiskLevel.AMBER: "Clinical review required",
    RiskLevel.RED: "URGENT: escalation required",
    RiskLevel.UNKNOWN: "Action needed: observations missing or stale",
}


# -- generation ------------------------------------------------------------


def build_notifications(
    state: PatientState,
    effective_risk: EffectiveRisk,
    interventions: list[Intervention],
    now: datetime,
) -> list[Notification]:
    """Generate messages for the actions that call for one. Sends nothing."""
    notifying = [
        i
        for i in interventions
        if i.action
        in (InterventionAction.NOTIFY_CLINICIAN, InterventionAction.NOTIFY_PATIENT)
    ]
    if not notifying:
        return []

    notifications: list[Notification] = []
    for intervention in notifying:
        audience = (
            NotificationAudience.PATIENT
            if intervention.action is InterventionAction.NOTIFY_PATIENT
            else NotificationAudience.CLINICIAN
        )
        notifications.append(
            Notification(
                notification_id=ids.new_id(ids.NOTIFICATION),
                patient_id=state.patient_id,
                trial_id=state.trial_id,
                audience=audience,
                channel=NotificationChannel.IN_APP,
                subject=f"{state.patient_id}: {_SUBJECTS[effective_risk.level]}",
                body=_body(state, effective_risk, interventions),
                created_at=now,
                intervention_id=intervention.intervention_id,
            )
        )
    return notifications


def _body(
    state: PatientState,
    effective_risk: EffectiveRisk,
    interventions: list[Intervention],
) -> str:
    lines = [
        f"Patient {state.patient_id} on trial {state.trial_id} is at "
        f"{effective_risk.level.value} under {protocol.PROTOCOL_ID}.",
        "",
        protocol.LEVEL_RATIONALE[effective_risk.level],
    ]

    if effective_risk.gated:
        lines += [
            "",
            f"Note: the risk model reported {effective_risk.provider_level.value}, "
            f"but {effective_risk.reason}",
        ]

    actions = [i for i in interventions if i.action not in (
        InterventionAction.NOTIFY_CLINICIAN, InterventionAction.NOTIFY_PATIENT
    )]
    if actions:
        lines += ["", "Protocol requires:"]
        lines += [f"  - {i.action.value.replace('_', ' ').lower()}" for i in actions]

    if state.data_quality.flags:
        lines += ["", "Data quality:"]
        lines += [f"  - {f.message}" for f in state.data_quality.flags]

    lines += ["", "Decision support only. This message does not authorise treatment."]
    return "\n".join(lines)


# -- delivery --------------------------------------------------------------


class NotificationDeliveryProvider(ABC):
    """Physically delivers a generated notification.

    Phase 2 ships only the in-app provider. Email/SMS/push implement this same
    interface later with no change to generation.
    """

    name: str = "abstract"

    @abstractmethod
    def deliver(self, notification: Notification, now: datetime) -> Notification:
        """Return the notification marked delivered. Must never raise."""
        raise NotImplementedError


class InAppNotificationProvider(NotificationDeliveryProvider):
    """Mock delivery: marks the message delivered so the UI can show it.

    There is no outbound network call anywhere in Phase 2.
    """

    name = "in-app-mock"

    def deliver(self, notification: Notification, now: datetime) -> Notification:
        if notification.channel is not NotificationChannel.IN_APP:
            # Nothing can actually send on other channels yet, so the message
            # stays undelivered rather than being falsely marked sent.
            return notification
        return notification.model_copy(
            update={"delivered_at": now, "delivery_provider": self.name}
        )
