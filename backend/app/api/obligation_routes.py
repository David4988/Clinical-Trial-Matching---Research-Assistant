"""Obligation-layer HTTP routes. Mounted under `/obligations`.

Conventions matched to `api/monitoring_routes.py`: `_context`, `_now`,
`_fail`, `_handle`, a per-router `_STATUS_BY_CODE` dict defaulting to 422.
`docs/FINAL_IMPLEMENTATION_PLAN.md` §23.

`/investigate` runs whichever `AgentModelProvider` `MODEL_PROVIDER` selects
(template/local/hosted) via `agent/investigate.py`; the response shape and
the approval boundary are identical regardless of which one answered —
only `provenance.provider_kind`/`.model_name` differ.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from .obligation_models import (
    ApproveProposalRequest,
    DismissObligationRequest,
    RecordResponseRequest,
    RejectProposalRequest,
)
from ..agent.classify import classify_response
from ..obligations import ids as obligation_ids
from ..obligations.context import ObligationContext
from ..obligations.service import ObligationError
from ..repository.base import RepositoryError
from ..schema.obligation_enums import ActorKind, ObligationActionKind
from ..schema.obligations import IncomingMessage, Obligation, ObligationAction, ProposedAction, QueueItem, ResponsibleParty

router = APIRouter(prefix="/obligations", tags=["obligations"])

_STATUS_BY_CODE = {
    "OBLIGATION_NOT_FOUND": 404,
    "PROPOSAL_NOT_FOUND": 404,
}


def _context(request: Request) -> ObligationContext:
    return request.app.state.obligations


def _now(supplied: datetime | None) -> datetime:
    return supplied or datetime.now(timezone.utc)


def _fail(status: int, code: str, message: str, details: list[str] | None = None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message, "details": details or []})


def _handle(exc: ObligationError):
    _fail(_STATUS_BY_CODE.get(exc.code, 422), exc.code, exc.message, exc.details)


@router.get("", response_model=dict)
def list_obligations(
    request: Request,
    trial_id: str = Query(...),
    patient_id: str | None = None,
    status: str | None = None,
    type: str | None = None,
    party_id: str | None = None,
) -> dict:
    ctx = _context(request)
    try:
        obligations = ctx.service.list(
            trial_id=trial_id, patient_id=patient_id, status=status, type=type, party_id=party_id
        )
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Obligations could not be read.", [str(exc)])
    return {"trial_id": trial_id, "count": len(obligations), "obligations": obligations}


@router.get("/queue", response_model=dict)
def get_queue(request: Request, trial_id: str = Query(...)) -> dict:
    from ..obligations.queue import build_queue

    ctx = _context(request)
    now = datetime.now(timezone.utc)
    try:
        obligations = ctx.service.list(trial_id=trial_id)
        proposals = ctx.repository.list_proposals(trial_id=trial_id)
        parties = {p.party_id: p for p in ctx.repository.list_parties(trial_id)}
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The queue could not be built.", [str(exc)])

    items = build_queue(obligations, proposals, parties, now)
    needs_decision = sum(1 for i in items if i.needs_human_decision)
    awaiting = sum(1 for i in items if i.status.value == "AWAITING_RESPONSE")
    return {
        "trial_id": trial_id,
        "generated_at": now,
        "counts": {"total": len(items), "needs_decision": needs_decision, "awaiting_response": awaiting},
        "items": items,
    }


@router.get("/parties", response_model=list[ResponsibleParty])
def list_parties(request: Request, trial_id: str | None = None) -> list[ResponsibleParty]:
    try:
        return _context(request).repository.list_parties(trial_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Parties could not be read.", [str(exc)])


@router.get("/incoming", response_model=list[IncomingMessage])
def list_incoming(request: Request, unmatched: bool = False) -> list[IncomingMessage]:
    try:
        return _context(request).repository.list_incoming_messages(unmatched=unmatched)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Incoming messages could not be read.", [str(exc)])


@router.get("/proposals", response_model=list[ProposedAction])
def list_proposals(request: Request, status: str | None = None, obligation_id: str | None = None) -> list[ProposedAction]:
    try:
        return _context(request).repository.list_proposals(status=status, obligation_id=obligation_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Proposals could not be read.", [str(exc)])


@router.get("/proposals/{proposal_id}", response_model=ProposedAction)
def get_proposal(request: Request, proposal_id: str) -> ProposedAction:
    try:
        proposal = _context(request).repository.get_proposal(proposal_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The proposal could not be read.", [str(exc)])
    if proposal is None:
        _fail(404, "PROPOSAL_NOT_FOUND", f"No proposal with id '{proposal_id}'.")
    return proposal


@router.post("/proposals/{proposal_id}/approve", response_model=ProposedAction)
def approve_proposal(request: Request, proposal_id: str, payload: ApproveProposalRequest) -> ProposedAction:
    ctx = _context(request)
    try:
        return ctx.proposals.approve(
            proposal_id,
            reviewer=payload.reviewer,
            note=payload.note,
            channel=payload.channel,
            edited_subject=payload.edited_subject,
            edited_body=payload.edited_body,
            now=_now(payload.now),
        )
    except ObligationError as exc:
        _handle(exc)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The approval could not be saved.", [str(exc)])


@router.post("/proposals/{proposal_id}/reject", response_model=ProposedAction)
def reject_proposal(request: Request, proposal_id: str, payload: RejectProposalRequest) -> ProposedAction:
    ctx = _context(request)
    try:
        return ctx.proposals.reject(proposal_id, reviewer=payload.reviewer, note=payload.note, now=_now(payload.now))
    except ObligationError as exc:
        _handle(exc)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The rejection could not be saved.", [str(exc)])


@router.get("/{obligation_id}", response_model=Obligation)
def get_obligation(request: Request, obligation_id: str) -> Obligation:
    try:
        obligation = _context(request).service.get(obligation_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The obligation could not be read.", [str(exc)])
    if obligation is None:
        _fail(404, "OBLIGATION_NOT_FOUND", f"No obligation with id '{obligation_id}'.")
    return obligation


@router.get("/{obligation_id}/actions", response_model=list[ObligationAction])
def get_actions(request: Request, obligation_id: str) -> list[ObligationAction]:
    try:
        return _context(request).service.list_actions(obligation_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The ledger could not be read.", [str(exc)])


@router.post("/{obligation_id}/investigate", response_model=ProposedAction, status_code=201)
def investigate(request: Request, obligation_id: str) -> ProposedAction:
    """Runs the deterministic template provider and returns a new `DRAFT`
    proposal. Body is deliberately empty: every input needed is already on
    the obligation (§23.4)."""
    ctx = _context(request)
    try:
        return ctx.proposals.propose(obligation_id)
    except ObligationError as exc:
        _handle(exc)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The proposal could not be saved.", [str(exc)])


@router.post("/{obligation_id}/dismiss", response_model=Obligation)
def dismiss(request: Request, obligation_id: str, payload: DismissObligationRequest) -> Obligation:
    ctx = _context(request)
    try:
        return ctx.service.dismiss(obligation_id, reviewer=payload.reviewer, note=payload.note, now=_now(payload.now))
    except ObligationError as exc:
        _handle(exc)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The dismissal could not be saved.", [str(exc)])


@router.post("/{obligation_id}/responses", response_model=ObligationAction, status_code=201)
def record_response(request: Request, obligation_id: str, payload: RecordResponseRequest) -> ObligationAction:
    """The manual demo + test path (§23.6): records an inbound reply
    without a live Gmail/WhatsApp round-trip. Classification only —
    `Obligation.status`, `.resolution` and every other field are
    byte-identical before and after."""
    ctx = _context(request)
    now = _now(payload.now)
    try:
        obligation = ctx.service.get(obligation_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The obligation could not be read.", [str(exc)])
    if obligation is None:
        _fail(404, "OBLIGATION_NOT_FOUND", f"No obligation with id '{obligation_id}'.")

    classification, confidence = classify_response(payload.text)
    action = ObligationAction(
        action_id=obligation_ids.new_id(obligation_ids.OBLIGATION_ACTION),
        obligation_id=obligation_id,
        seq=obligation.action_count + 1,
        kind=ObligationActionKind.RESPONSE_RECEIVED,
        occurred_at=now,
        actor_kind=ActorKind.SYSTEM,
        recipient_party_id=payload.from_party_id,
        note=payload.text,
        payload={"classification": classification.value, "confidence": confidence},
    )
    try:
        ctx.service.attach_action(obligation, action)
    except ObligationError as exc:
        _handle(exc)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The response could not be saved.", [str(exc)])
    return action
