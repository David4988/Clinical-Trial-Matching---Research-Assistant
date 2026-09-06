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
from ..schema.obligations import (
    ApprovalRecord,
    IncomingMessage,
    Obligation,
    ObligationAction,
    ProposedAction,
    ResponsibleParty,
)
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
        "proposal_id": notification.proposal_id,
        "document": notification.model_dump(mode="json"),
    }


def row_to_notification(row: Row) -> Notification:
    return Notification.model_validate(row["document"])


# -- responsible parties -------------------------------------------------------


def party_to_row(party: ResponsibleParty) -> dict[str, Any]:
    return {
        "party_id": party.party_id,
        "display_name": party.display_name,
        "role": party.role.value,
        "site_id": party.site_id,
        "email": party.email,
        "phone": party.phone,
        "preferred_channel": party.preferred_channel.value,
        "trial_ids": party.trial_ids,
    }


def row_to_party(row: Row) -> ResponsibleParty:
    return ResponsibleParty.model_validate(
        {
            "party_id": row["party_id"],
            "display_name": row["display_name"],
            "role": row["role"],
            "site_id": row["site_id"],
            "email": row["email"],
            "phone": row["phone"],
            "preferred_channel": row["preferred_channel"],
            "trial_ids": row["trial_ids"],
        }
    )


# -- obligations -----------------------------------------------------------


def obligation_to_row(obligation: Obligation) -> dict[str, Any]:
    resolution = obligation.resolution
    return {
        "obligation_id": obligation.obligation_id,
        "obligation_key": obligation.obligation_key,
        "trial_id": obligation.trial_id,
        "patient_id": obligation.patient_id,
        "type": obligation.type.value,
        "status": obligation.status.value,
        "priority": obligation.priority.value,
        "requirement_ref": obligation.requirement_ref,
        "requirement_text": obligation.requirement_text,
        "protocol_id": obligation.protocol_id,
        "source_ref": obligation.source_ref,
        "detector_source": obligation.detector_source,
        "occurrence": obligation.occurrence,
        "title": obligation.title,
        "detail": obligation.detail,
        "evidence": [e.model_dump(mode="json") for e in obligation.evidence],
        "first_detected_at": obligation.first_detected_at,
        "last_confirmed_at": obligation.last_confirmed_at,
        "due_at": obligation.due_at,
        "responsible_party_id": obligation.responsible_party_id,
        "escalation_count": obligation.escalation_count,
        "action_count": obligation.action_count,
        "last_action_at": obligation.last_action_at,
        "resolved_at": obligation.resolved_at,
        "resolution_kind": resolution.kind.value if resolution else None,
        "resolution_by": resolution.by if resolution else None,
        "resolution_note": resolution.note if resolution else None,
        "resolution_at": resolution.at if resolution else None,
    }


def row_to_obligation(row: Row) -> Obligation:
    resolution = None
    if row["resolution_kind"] is not None:
        resolution = {
            "kind": row["resolution_kind"],
            "by": row["resolution_by"],
            "note": row["resolution_note"],
            "at": row["resolution_at"],
        }
    return Obligation.model_validate(
        {
            "obligation_id": row["obligation_id"],
            "obligation_key": row["obligation_key"],
            "trial_id": row["trial_id"],
            "patient_id": row["patient_id"],
            "type": row["type"],
            "status": row["status"],
            "priority": row["priority"],
            "requirement_ref": row["requirement_ref"],
            "requirement_text": row["requirement_text"],
            "protocol_id": row["protocol_id"],
            "source_ref": row["source_ref"],
            "detector_source": row["detector_source"],
            "occurrence": row["occurrence"],
            "title": row["title"],
            "detail": row["detail"],
            "evidence": row["evidence"],
            "first_detected_at": row["first_detected_at"],
            "last_confirmed_at": row["last_confirmed_at"],
            "due_at": row["due_at"],
            "responsible_party_id": row["responsible_party_id"],
            "escalation_count": row["escalation_count"],
            "action_count": row["action_count"],
            "last_action_at": row["last_action_at"],
            "resolved_at": row["resolved_at"],
            "resolution": resolution,
        }
    )


# -- obligation actions (follow-up ledger) ----------------------------------


def obligation_action_to_row(action: ObligationAction) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "obligation_id": action.obligation_id,
        "seq": action.seq,
        "kind": action.kind.value,
        "occurred_at": action.occurred_at,
        "actor_kind": action.actor_kind.value,
        "actor_name": action.actor_name,
        "channel": action.channel.value if action.channel else None,
        "recipient_party_id": action.recipient_party_id,
        "ref_id": action.ref_id,
        "note": action.note,
        "payload": action.payload,
    }


def row_to_obligation_action(row: Row) -> ObligationAction:
    return ObligationAction.model_validate(
        {
            "action_id": row["action_id"],
            "obligation_id": row["obligation_id"],
            "seq": row["seq"],
            "kind": row["kind"],
            "occurred_at": row["occurred_at"],
            "actor_kind": row["actor_kind"],
            "actor_name": row["actor_name"],
            "channel": row["channel"],
            "recipient_party_id": row["recipient_party_id"],
            "ref_id": row["ref_id"],
            "note": row["note"],
            "payload": row["payload"],
        }
    )


# -- proposed actions --------------------------------------------------------


def proposed_action_to_row(proposal: ProposedAction) -> dict[str, Any]:
    prov = proposal.provenance
    dec = proposal.decision
    ex = proposal.execution
    return {
        "proposal_id": proposal.proposal_id,
        "obligation_ids": proposal.obligation_ids,
        "trial_id": proposal.trial_id,
        "patient_ids": proposal.patient_ids,
        "action_type": proposal.action_type.value,
        "status": proposal.status.value,
        "recipient_party_id": proposal.recipient_party_id,
        "channel": proposal.channel.value,
        "subject": proposal.subject,
        "body": proposal.body,
        "reason": proposal.reason,
        "evidence": [e.model_dump(mode="json") for e in proposal.evidence],
        "template_name": proposal.template_name,
        "template_params": proposal.template_params,
        "created_at": proposal.created_at,
        "prov_generated_by": prov.generated_by,
        "prov_provider_kind": prov.provider_kind.value,
        "prov_model_name": prov.model_name,
        "prov_prompt_version": prov.prompt_version,
        "prov_latency_ms": prov.latency_ms,
        "prov_degraded": prov.degraded,
        "prov_tools_called": prov.tools_called,
        "prov_evidence_ids": prov.evidence_ids,
        "prov_unresolved": prov.unresolved,
        "dec_outcome": dec.outcome if dec else None,
        "dec_reviewer": dec.reviewer if dec else None,
        "dec_note": dec.note if dec else None,
        "dec_decided_at": dec.decided_at if dec else None,
        "dec_edited_subject": dec.edited_subject if dec else None,
        "dec_edited_body": dec.edited_body if dec else None,
        "exec_executed_at": ex.executed_at if ex else None,
        "exec_provider": ex.provider if ex else None,
        "exec_channel": ex.channel.value if ex else None,
        "exec_notification_id": ex.notification_id if ex else None,
        "exec_provider_message_id": ex.provider_message_id if ex else None,
        "exec_provider_thread_id": ex.provider_thread_id if ex else None,
        "exec_delivery_status": ex.delivery_status.value if ex else None,
        "exec_error": ex.error if ex else None,
    }


def row_to_proposed_action(row: Row) -> ProposedAction:
    decision = None
    if row["dec_outcome"] is not None:
        decision = {
            "outcome": row["dec_outcome"],
            "reviewer": row["dec_reviewer"],
            "note": row["dec_note"],
            "decided_at": row["dec_decided_at"],
            "edited_subject": row["dec_edited_subject"],
            "edited_body": row["dec_edited_body"],
        }
    execution = None
    if row["exec_executed_at"] is not None:
        execution = {
            "executed_at": row["exec_executed_at"],
            "provider": row["exec_provider"],
            "channel": row["exec_channel"],
            "notification_id": row["exec_notification_id"],
            "provider_message_id": row["exec_provider_message_id"],
            "provider_thread_id": row["exec_provider_thread_id"],
            "delivery_status": row["exec_delivery_status"] or "UNKNOWN",
            "error": row["exec_error"],
        }
    return ProposedAction.model_validate(
        {
            "proposal_id": row["proposal_id"],
            "obligation_ids": row["obligation_ids"],
            "trial_id": row["trial_id"],
            "patient_ids": row["patient_ids"],
            "action_type": row["action_type"],
            "status": row["status"],
            "recipient_party_id": row["recipient_party_id"],
            "channel": row["channel"],
            "subject": row["subject"],
            "body": row["body"],
            "reason": row["reason"],
            "evidence": row["evidence"],
            "template_name": row["template_name"],
            "template_params": row["template_params"],
            "created_at": row["created_at"],
            "provenance": {
                "generated_by": row["prov_generated_by"],
                "provider_kind": row["prov_provider_kind"],
                "model_name": row["prov_model_name"],
                "prompt_version": row["prov_prompt_version"],
                "latency_ms": row["prov_latency_ms"],
                "tools_called": row["prov_tools_called"],
                "evidence_ids": row["prov_evidence_ids"],
                "degraded": row["prov_degraded"],
                "unresolved": row["prov_unresolved"],
            },
            "decision": decision,
            "execution": execution,
        }
    )


# -- approval records ---------------------------------------------------------


def approval_record_to_row(approval: ApprovalRecord) -> dict[str, Any]:
    return {
        "proposal_id": approval.proposal_id,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at,
        "channel": approval.channel.value,
        "subject": approval.subject,
        "body": approval.body,
        "template_name": approval.template_name,
        "template_params": approval.template_params,
        "recipient_email": approval.recipient_email,
        "recipient_phone": approval.recipient_phone,
    }


def row_to_approval_record(row: Row) -> ApprovalRecord:
    return ApprovalRecord.model_validate(
        {
            "proposal_id": row["proposal_id"],
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"],
            "channel": row["channel"],
            "subject": row["subject"],
            "body": row["body"],
            "template_name": row["template_name"],
            "template_params": row["template_params"],
            "recipient_email": row["recipient_email"],
            "recipient_phone": row["recipient_phone"],
        }
    )


# -- incoming messages (inbound) ---------------------------------------------


def incoming_message_to_row(message: IncomingMessage) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "channel": message.channel.value,
        "provider_message_id": message.provider_message_id,
        "provider_thread_id": message.provider_thread_id,
        "from_party_id": message.from_party_id,
        "obligation_id": message.obligation_id,
        "received_at": message.received_at,
        "body_text": message.body_text,
        "classification": message.classification.value if message.classification else None,
        "confidence": message.confidence,
    }


def row_to_incoming_message(row: Row) -> IncomingMessage:
    return IncomingMessage.model_validate(
        {
            "message_id": row["message_id"],
            "channel": row["channel"],
            "provider_message_id": row["provider_message_id"],
            "provider_thread_id": row["provider_thread_id"],
            "from_party_id": row["from_party_id"],
            "obligation_id": row["obligation_id"],
            "received_at": row["received_at"],
            "body_text": row["body_text"],
            "classification": row["classification"],
            "confidence": row["confidence"],
        }
    )
