"""Reconciliation: CREATE / TOUCH / AUTO-RESOLVE.

A pure function — no repository handle, no clock read, no I/O, no model
call. `obligations/service.py` is its only caller and the only thing that
persists the returned delta. `docs/FINAL_IMPLEMENTATION_PLAN.md` §6.4.
"""

from __future__ import annotations

from datetime import datetime

from . import ids, rules
from .rules import reconfirm_interval_hours
from ..schema.enums import CriterionKind
from ..schema.obligation_enums import ActorKind, ObligationActionKind, ObligationStatus, ResolutionKind
from ..schema.obligations import (
    DetectedRequirement,
    Obligation,
    ObligationAction,
    ObligationDelta,
    ObligationResolution,
)


def reconcile(
    *,
    trial_id: str,
    patient_id: str,
    detector_source: str,
    detected: list[DetectedRequirement],
    existing: list[Obligation],
    now: datetime,
    criterion_kind_by_ref: dict[str, CriterionKind] | None = None,
    has_active_treatment: bool = False,
    responsible_party_id_for: "callable | None" = None,
) -> ObligationDelta:
    """`existing` MUST be pre-filtered by the caller to exactly every
    non-terminal obligation for this `(trial_id, patient_id, source)` and no
    others — the `DetectionScope` safety mechanism. A detector run that
    raised must never reach this function."""

    criterion_kind_by_ref = criterion_kind_by_ref or {}
    existing_by_key = {o.obligation_key: o for o in existing}
    detected_keys: set[str] = set()

    delta = ObligationDelta()

    for req in detected:
        key = rules.obligation_key(req.trial_id, req.patient_id, req.type, req.requirement_ref, req.occurrence)
        detected_keys.add(key)
        current = existing_by_key.get(key)

        party_id = responsible_party_id_for(req) if responsible_party_id_for else None
        kind = criterion_kind_by_ref.get(req.requirement_ref)

        if current is None:
            age_days = 0
            priority = rules.priority_for(
                criterion_kind=kind,
                has_active_treatment=has_active_treatment,
                age_days=age_days,
                escalation_count=0,
            )
            obligation = Obligation(
                obligation_id=ids.new_id(ids.OBLIGATION),
                obligation_key=key,
                trial_id=req.trial_id,
                patient_id=req.patient_id,
                type=req.type,
                status=ObligationStatus.OPEN,
                priority=priority,
                requirement_ref=req.requirement_ref,
                requirement_text=req.requirement_text,
                protocol_id=req.protocol_id,
                source_ref=req.source_ref,
                detector_source=detector_source,
                occurrence=req.occurrence,
                title=rules.title_for(req.type, req.requirement_ref, req.requirement_text),
                detail=rules.detail_for(req.type, req.requirement_ref, req.requirement_text, req.patient_id),
                evidence=req.evidence,
                first_detected_at=now,
                last_confirmed_at=now,
                due_at=req.due_at,
                responsible_party_id=party_id,
                action_count=1,
                last_action_at=now,
            )
            action = ObligationAction(
                action_id=ids.new_id(ids.OBLIGATION_ACTION),
                obligation_id=obligation.obligation_id,
                seq=1,
                kind=ObligationActionKind.DETECTED,
                occurred_at=now,
                actor_kind=ActorKind.SYSTEM,
                recipient_party_id=party_id,
            )
            delta.created.append(obligation)
            delta.created_actions.append(action)
        else:
            age_days = (now - current.first_detected_at).days
            priority = rules.priority_for(
                criterion_kind=kind,
                has_active_treatment=has_active_treatment,
                age_days=age_days,
                escalation_count=current.escalation_count,
            )
            due = (
                current.last_action_at is None
                or (now - current.last_action_at).total_seconds() >= reconfirm_interval_hours() * 3600
            )
            touched = current.model_copy(
                update={
                    "last_confirmed_at": now,
                    "title": rules.title_for(req.type, req.requirement_ref, req.requirement_text),
                    "detail": rules.detail_for(req.type, req.requirement_ref, req.requirement_text, req.patient_id),
                    "evidence": req.evidence,
                    "priority": priority,
                    "responsible_party_id": party_id,
                    "action_count": current.action_count + (1 if due else 0),
                    "last_action_at": now if due else current.last_action_at,
                }
            )
            delta.touched.append(touched)

            if due:
                delta.touched_actions.append(
                    ObligationAction(
                        action_id=ids.new_id(ids.OBLIGATION_ACTION),
                        obligation_id=current.obligation_id,
                        seq=current.action_count + 1,
                        kind=ObligationActionKind.RECONFIRMED,
                        occurred_at=now,
                        actor_kind=ActorKind.SYSTEM,
                        recipient_party_id=party_id,
                    )
                )

    for key, current in existing_by_key.items():
        if key in detected_keys:
            continue
        resolved = current.model_copy(
            update={
                "status": ObligationStatus.RESOLVED,
                "resolved_at": now,
                "resolution": ObligationResolution(
                    kind=ResolutionKind.SATISFIED,
                    by="SYSTEM",
                    note="The detector no longer reports this requirement as outstanding.",
                    at=now,
                ),
                "action_count": current.action_count + 1,
                "last_action_at": now,
            }
        )
        delta.auto_resolved.append(resolved)
        delta.auto_resolved_actions.append(
            ObligationAction(
                action_id=ids.new_id(ids.OBLIGATION_ACTION),
                obligation_id=current.obligation_id,
                seq=current.action_count + 1,
                kind=ObligationActionKind.RESOLVED,
                occurred_at=now,
                actor_kind=ActorKind.SYSTEM,
            )
        )

    return delta
