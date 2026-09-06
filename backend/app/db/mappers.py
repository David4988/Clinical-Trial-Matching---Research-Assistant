"""Row <-> Pydantic conversion. The only module that knows a column name.

Every function is a pure pair: `<entity>_to_row` produces the dict passed to
an `insert()`/`update()`, `row_to_<entity>` reconstructs the Pydantic model
from a fetched row (a `RowMapping` or an equivalent `dict`). Hybrid document
tables (Group A) round-trip through `model_dump(mode="json")` /
`model_validate`, exactly as the JSON repositories already do — the port is
mechanical by design (`docs/FINAL_IMPLEMENTATION_PLAN.md` §11.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ..schema.clinical import Patient
from ..schema.monitoring import AdverseEvent, Observation, TreatmentAssignment
from ..schema.monitoring_result import MonitoringCycleResult, MonitoringEvent, Notification
from ..schema.result import ScreeningResult
from ..schema.trial import Trial

Row = Mapping[str, Any]


# -- patients ----------------------------------------------------------------


def patient_to_row(patient: Patient, now: datetime) -> dict[str, Any]:
    return {
        "patient_id": patient.patient_id,
        "document": patient.model_dump(mode="json"),
        "updated_at": now,
    }


def row_to_patient(row: Row) -> Patient:
    return Patient.model_validate(row["document"])


# -- trials -------------------------------------------------------------------


def trial_to_row(trial: Trial, now: datetime) -> dict[str, Any]:
    return {
        "trial_id": trial.trial_id,
        "title": trial.title,
        "document": trial.model_dump(mode="json"),
        "updated_at": now,
    }


def row_to_trial(row: Row) -> Trial:
    return Trial.model_validate(row["document"])


# -- screening results ---------------------------------------------------------


def screening_result_to_row(result: ScreeningResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "patient_id": result.patient.patient_id,
        "trial_id": result.trial.trial_id,
        "overall_status": result.overall_status.value,
        "generated_at": result.generated_at,
        "document": result.model_dump(mode="json"),
    }


def row_to_screening_result(row: Row) -> ScreeningResult:
    return ScreeningResult.model_validate(row["document"])


# -- treatments ----------------------------------------------------------------


def treatment_to_row(treatment: TreatmentAssignment) -> dict[str, Any]:
    return {
        "treatment_id": treatment.treatment_id,
        "patient_id": treatment.patient_id,
        "trial_id": treatment.trial_id,
        "screening_result_id": treatment.screening_result_id,
        "status": treatment.status.value,
        "registered_at": treatment.registered_at,
        "document": treatment.model_dump(mode="json"),
    }


def row_to_treatment(row: Row) -> TreatmentAssignment:
    return TreatmentAssignment.model_validate(row["document"])


# -- monitoring cycles -----------------------------------------------------------


def monitoring_cycle_to_row(cycle: MonitoringCycleResult) -> dict[str, Any]:
    return {
        "cycle_id": cycle.cycle_id,
        "patient_id": cycle.patient_id,
        "trial_id": cycle.trial_id,
        "generated_at": cycle.generated_at,
        "risk_level": cycle.effective_risk.level.value if cycle.effective_risk else None,
        "document": cycle.model_dump(mode="json"),
    }


def row_to_monitoring_cycle(row: Row) -> MonitoringCycleResult:
    return MonitoringCycleResult.model_validate(row["document"])


# -- observations ------------------------------------------------------------


def observation_to_row(observation: Observation) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "patient_id": observation.patient_id,
        "trial_id": observation.trial_id,
        "recorded_at": observation.recorded_at,
        "source": observation.source.value,
        "measurement_type": observation.measurement_type.value,
        "value": observation.value,
        "unit": observation.unit,
        "device_id": observation.device_id,
        "quality_note": observation.quality_note,
    }


def row_to_observation(row: Row) -> Observation:
    return Observation.model_validate(
        {
            "observation_id": row["observation_id"],
            "patient_id": row["patient_id"],
            "trial_id": row["trial_id"],
            "recorded_at": row["recorded_at"],
            "source": row["source"],
            "measurement_type": row["measurement_type"],
            "value": row["value"],
            "unit": row["unit"],
            "device_id": row["device_id"],
            "quality_note": row["quality_note"],
        }
    )


# -- adverse events ------------------------------------------------------------


def adverse_event_to_row(event: AdverseEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "patient_id": event.patient_id,
        "trial_id": event.trial_id,
        "term": event.term,
        "severity": event.severity.value,
        "onset_at": event.onset_at,
        "resolved_at": event.resolved_at,
        "reported_by": event.reported_by,
        "note": event.note,
    }


def row_to_adverse_event(row: Row) -> AdverseEvent:
    return AdverseEvent.model_validate(
        {
            "event_id": row["event_id"],
            "patient_id": row["patient_id"],
            "trial_id": row["trial_id"],
            "term": row["term"],
            "severity": row["severity"],
            "onset_at": row["onset_at"],
            "resolved_at": row["resolved_at"],
            "reported_by": row["reported_by"],
            "note": row["note"],
        }
    )


# -- monitoring events (timeline) ----------------------------------------------


def monitoring_event_to_row(event: MonitoringEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "patient_id": event.patient_id,
        "trial_id": event.trial_id,
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at,
        "summary": event.summary,
        "ref_id": event.ref_id,
        "payload": event.payload,
    }


def row_to_monitoring_event(row: Row) -> MonitoringEvent:
    return MonitoringEvent.model_validate(
        {
            "event_id": row["event_id"],
            "patient_id": row["patient_id"],
            "trial_id": row["trial_id"],
            "event_type": row["event_type"],
            "occurred_at": row["occurred_at"],
            "summary": row["summary"],
            "ref_id": row["ref_id"],
            "payload": row["payload"],
        }
    )


# -- notifications --------------------------------------------------------------


def notification_to_row(notification: Notification) -> dict[str, Any]:
    return {
        "notification_id": notification.notification_id,
        "patient_id": notification.patient_id,
        "trial_id": notification.trial_id,
        "channel": notification.channel.value,
        "audience": notification.audience.value,
        "created_at": notification.created_at,
        "document": notification.model_dump(mode="json"),
    }


def row_to_notification(row: Row) -> Notification:
    return Notification.model_validate(row["document"])
