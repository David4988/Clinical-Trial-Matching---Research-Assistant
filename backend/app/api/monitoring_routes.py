"""Phase 2 HTTP routes.

Mounted under `/monitoring`. Phase 1's routes are untouched and keep their
existing paths, so nothing that worked before moves.

Responses are canonical monitoring models. Errors reuse the Phase 1 envelope —
`{"error": {code, message, details}}` — because the app-level exception handlers
in `main.py` already produce it, and the frontend already knows how to render it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from .monitoring_models import (
    AdvanceMonitoringRequest,
    IngestObservationsRequest,
    RecordAdverseEventRequest,
    RecordDoseRequest,
    RecordInvestigatorReviewRequest,
    RegisterTreatmentRequest,
    RunCycleRequest,
    SeedDemoRequest,
)
from ..fixtures_loader import load_patient, load_trial
from ..monitoring import ids, protocol
from ..monitoring.context import MonitoringContext
from ..monitoring.errors import MonitoringError
from ..repository.base import RepositoryError
from ..risk.factory import build_risk_provider
from ..schema.monitoring import (
    AdverseEvent,
    InvestigatorReview,
    Observation,
    TreatmentAssignment,
)
from ..schema.monitoring_result import (
    IngestionResult,
    MonitoringCycleResult,
    MonitoringEvent,
    Notification,
    PatientState,
)
from ..synthetic.generator import COHORT, generate_windowed

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

#: MonitoringError codes that are not "the request was unprocessable".
_STATUS_BY_CODE = {
    "SCREENING_NOT_FOUND": 404,
    "TREATMENT_NOT_FOUND": 404,
    "CYCLE_NOT_FOUND": 404,
    "NO_CYCLE": 404,
    "TREATMENT_ALREADY_ACTIVE": 409,
    "REVIEW_PENDING": 409,
}


def _context(request: Request) -> MonitoringContext:
    return request.app.state.monitoring


def _now(supplied: datetime | None) -> datetime:
    """Explicit clock when given, server clock otherwise.

    Letting a caller pass `now` is what makes a demo replayable and keeps the
    API testable without freezing time globally.
    """
    return supplied or datetime.now(timezone.utc)


def _fail(status: int, code: str, message: str, details: list[str] | None = None):
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": message, "details": details or []},
    )


def _handle(exc: MonitoringError):
    _fail(_STATUS_BY_CODE.get(exc.code, 422), exc.code, exc.message, exc.details)


# -- protocol transparency -------------------------------------------------


@router.get("/protocol")
def get_protocol() -> dict:
    """Expose the demo protocol so the UI can label its numbers as synthetic."""
    return {
        "protocol_id": protocol.PROTOCOL_ID,
        "label": protocol.PROTOCOL_LABEL,
        "synthetic": True,
        "warning": (
            "Every threshold here is invented for demonstration. It is not "
            "clinical guidance and must not be used to interpret a real patient."
        ),
        "normal_band": {m.value: list(b) for m, b in protocol.NORMAL_BAND.items()},
        "concern_band": {m.value: list(b) for m, b in protocol.CONCERN_BAND.items()},
        "plausible_range": {
            m.value: list(b) for m, b in protocol.PLAUSIBLE_RANGE.items()
        },
        "expected_units": {m.value: u for m, u in protocol.EXPECTED_UNITS.items()},
        "risk_bands": {
            "green_below": protocol.GREEN_BELOW,
            "amber_below": protocol.AMBER_BELOW,
        },
        "monitoring_interval_minutes": {
            level.value: minutes
            for level, minutes in protocol.MONITORING_INTERVAL_MINUTES.items()
        },
        "actions_by_level": {
            level.value: [a.value for a in actions]
            for level, actions in protocol.ACTIONS_BY_LEVEL.items()
        },
        "stale_after_minutes": int(protocol.STALE_AFTER.total_seconds() // 60),
        "required_measurements": [m.value for m in protocol.REQUIRED_MEASUREMENTS],
    }


# -- treatments ------------------------------------------------------------


@router.post("/treatments", response_model=TreatmentAssignment)
def register_treatment(
    request: Request, payload: RegisterTreatmentRequest
) -> TreatmentAssignment:
    """Enter Phase 2 from a Phase 1 screening result."""
    try:
        return _context(request).treatment.register(
            screening_result_id=payload.screening_result_id,
            drug_name=payload.drug_name,
            now=_now(payload.now),
            course_label=payload.course_label,
            override_by=payload.override_by,
            override_reason=payload.override_reason,
        )
    except MonitoringError as exc:
        _handle(exc)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The treatment could not be saved.", [str(exc)])


@router.get("/treatments", response_model=list[TreatmentAssignment])
def list_treatments(
    request: Request,
    trial_id: str | None = Query(default=None),
    patient_id: str | None = Query(default=None),
) -> list[TreatmentAssignment]:
    try:
        return _context(request).repository.list_treatments(
            trial_id=trial_id, patient_id=patient_id
        )
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Treatments could not be read.", [str(exc)])


@router.get("/treatments/{treatment_id}", response_model=TreatmentAssignment)
def get_treatment(request: Request, treatment_id: str) -> TreatmentAssignment:
    treatment = _context(request).repository.get_treatment(treatment_id)
    if treatment is None:
        _fail(404, "TREATMENT_NOT_FOUND", f"No treatment with id '{treatment_id}'.")
    return treatment


@router.post("/treatments/{treatment_id}/doses", response_model=TreatmentAssignment)
def record_dose(
    request: Request, treatment_id: str, payload: RecordDoseRequest
) -> TreatmentAssignment:
    try:
        return _context(request).treatment.record_dose(
            treatment_id=treatment_id,
            amount=payload.amount,
            unit=payload.unit,
            now=_now(payload.now),
            administered_by=payload.administered_by,
            note=payload.note,
            route=payload.route,
        )
    except MonitoringError as exc:
        _handle(exc)


# -- observations ----------------------------------------------------------


@router.post("/observations", response_model=IngestionResult)
def ingest_observations(
    request: Request, payload: IngestObservationsRequest
) -> IngestionResult:
    """Batch ingest. Invalid rows are refused and reported, never dropped."""
    observations = [
        Observation(observation_id=ids.new_id(ids.OBSERVATION), **row.model_dump())
        for row in payload.observations
    ]
    try:
        return _context(request).ingestion.ingest(observations, now=_now(payload.now))
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Observations could not be saved.", [str(exc)])


@router.get("/patients/{patient_id}/observations", response_model=list[Observation])
def list_observations(
    request: Request, patient_id: str, trial_id: str | None = Query(default=None)
) -> list[Observation]:
    return _context(request).repository.list_observations(patient_id, trial_id=trial_id)


# -- adverse events --------------------------------------------------------


@router.post("/adverse-events", response_model=AdverseEvent)
def record_adverse_event(
    request: Request, payload: RecordAdverseEventRequest
) -> AdverseEvent:
    event = AdverseEvent(
        event_id=ids.new_id(ids.ADVERSE_EVENT),
        patient_id=payload.patient_id,
        trial_id=payload.trial_id,
        term=payload.term,
        severity=payload.severity,
        onset_at=payload.onset_at or datetime.now(timezone.utc),
        resolved_at=payload.resolved_at,
        reported_by=payload.reported_by,
        note=payload.note,
    )
    _context(request).repository.save_adverse_event(event)
    return event


@router.get("/patients/{patient_id}/adverse-events", response_model=list[AdverseEvent])
def list_adverse_events(request: Request, patient_id: str) -> list[AdverseEvent]:
    return _context(request).repository.list_adverse_events(patient_id)


# -- state, cycles, timeline ----------------------------------------------


@router.get("/patients/{patient_id}/state", response_model=PatientState)
def get_patient_state(
    request: Request,
    patient_id: str,
    trial_id: str = Query(...),
    now: datetime | None = Query(default=None),
) -> PatientState:
    """The derived projection. Recomputed on read, never stored."""
    from ..monitoring.state import build_patient_state

    context = _context(request)
    at = _now(now)
    treatments = context.repository.list_treatments(
        trial_id=trial_id, patient_id=patient_id
    )
    return build_patient_state(
        patient_id=patient_id,
        trial_id=trial_id,
        observations=context.repository.list_observations(patient_id, trial_id=trial_id),
        now=at,
        treatment=treatments[-1] if treatments else None,
        adverse_events=context.repository.list_adverse_events(patient_id),
    )


@router.post("/patients/{patient_id}/cycle", response_model=MonitoringCycleResult)
def run_cycle(
    request: Request, patient_id: str, payload: RunCycleRequest
) -> MonitoringCycleResult:
    """Run one monitoring cycle: state -> risk -> gate -> protocol -> next dose."""
    try:
        return _context(request).monitoring.run_cycle(
            patient_id, payload.trial_id, _now(payload.now)
        )
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The cycle could not be saved.", [str(exc)])


@router.get("/patients/{patient_id}/cycle", response_model=MonitoringCycleResult)
def latest_cycle(request: Request, patient_id: str) -> MonitoringCycleResult:
    cycle = _context(request).monitoring.latest_cycle(patient_id)
    if cycle is None:
        _fail(
            404,
            "NO_CYCLE",
            f"No monitoring cycle has been run for '{patient_id}'.",
            ["Ingest observations and run a cycle first."],
        )
    return cycle


@router.get("/patients/{patient_id}/cycles", response_model=list[MonitoringCycleResult])
def list_cycles(request: Request, patient_id: str) -> list[MonitoringCycleResult]:
    return _context(request).repository.list_cycles(patient_id)


@router.post("/patients/{patient_id}/advance", response_model=MonitoringCycleResult)
def advance_monitoring(
    request: Request, patient_id: str, payload: AdvanceMonitoringRequest
) -> MonitoringCycleResult:
    """Play one synthetic observation window for one enrolled participant.

    The single-participant counterpart to `/demo/seed`. It runs the same two
    steps that endpoint runs per window — ingest, then `run_cycle` — so the
    resulting cycle is produced by the ordinary pipeline and by the ordinary
    risk provider. Nothing here computes or overrides a risk level.

    Synthetic data only: every observation carries `ObservationSource.SYNTHETIC`.
    """
    context = _context(request)

    treatments = context.repository.list_treatments(
        trial_id=payload.trial_id, patient_id=patient_id
    )
    if not treatments:
        _fail(
            404,
            "TREATMENT_NOT_FOUND",
            f"{patient_id} is not enrolled on {payload.trial_id}.",
            ["Register a treatment before advancing monitoring."],
        )

    if payload.window_index >= payload.windows:
        _fail(
            422,
            "WINDOW_OUT_OF_RANGE",
            f"window_index {payload.window_index} is beyond the "
            f"{payload.windows} generated windows.",
        )

    batches = generate_windowed(
        patient_id,
        payload.trial_id,
        payload.trajectory,
        payload.start or treatments[-1].registered_at,
        windows=payload.windows,
        hours=payload.hours,
        interval_minutes=payload.interval_minutes,
        seed=payload.seed,
    )
    batch = batches[payload.window_index]
    at = max(o.recorded_at for o in batch)

    try:
        context.ingestion.ingest(batch, now=at)
        return context.monitoring.run_cycle(patient_id, payload.trial_id, at)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The cycle could not be saved.", [str(exc)])


@router.post(
    "/patients/{patient_id}/investigator-review", response_model=InvestigatorReview
)
def record_investigator_review(
    request: Request, patient_id: str, payload: RecordInvestigatorReviewRequest
) -> InvestigatorReview:
    """Record a named investigator's decision about a monitoring cycle.

    The decision is appended to the timeline. It does not change the cycle's
    risk level or its interventions — those stay exactly as the protocol layer
    produced them. `HOLD_TREATMENT` is the only action with a further effect,
    and it places the treatment ON_HOLD through the treatment service.
    """
    try:
        return _context(request).investigator.record(
            patient_id=patient_id,
            action=payload.action,
            reviewer=payload.reviewer,
            note=payload.note,
            now=_now(payload.now),
            cycle_id=payload.cycle_id,
        )
    except MonitoringError as exc:
        _handle(exc)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The review could not be saved.", [str(exc)])


@router.get(
    "/patients/{patient_id}/investigator-reviews",
    response_model=list[InvestigatorReview],
)
def list_investigator_reviews(
    request: Request, patient_id: str
) -> list[InvestigatorReview]:
    return _context(request).investigator.list_for_patient(patient_id)


@router.get("/patients/{patient_id}/timeline", response_model=list[MonitoringEvent])
def timeline(request: Request, patient_id: str) -> list[MonitoringEvent]:
    """Dose -> observations -> risk -> transitions -> alerts -> next dose."""
    return _context(request).monitoring.timeline(patient_id)


@router.get("/patients/{patient_id}/notifications", response_model=list[Notification])
def patient_notifications(request: Request, patient_id: str) -> list[Notification]:
    return _context(request).repository.list_notifications(patient_id)


# -- dashboard -------------------------------------------------------------


@router.get("/trials/{trial_id}/overview")
def trial_overview(request: Request, trial_id: str) -> dict:
    """Aggregate for the Trial Overview screen."""
    try:
        return _context(request).monitoring.trial_overview(trial_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The overview could not be built.", [str(exc)])


# -- demo seeding ----------------------------------------------------------


@router.post("/demo/seed")
def seed_demo(request: Request, payload: SeedDemoRequest) -> dict:
    """Populate the demo cohort end to end. Development and demonstration only.

    Runs the *real* pipeline for each patient — Phase 1 screening, treatment
    registration, ingestion, then a monitoring cycle per window — so the
    dashboard is populated by the same code path a live patient would take.
    """
    context = _context(request)
    screening_service = request.app.state.service
    start = payload.start or datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)

    # `use_synthetic_ml` predates the three-provider split and meant "replay the
    # precomputed research fixtures", so it maps to "synthetic", not to the live
    # model. `risk_provider` is the explicit form and wins when both are given.
    chosen = payload.risk_provider or (
        "synthetic" if payload.use_synthetic_ml else None
    )
    if chosen:
        context = MonitoringContext.build(
            screening_repository=request.app.state.service.repository,
            monitoring_repository=context.repository,
            risk_provider=build_risk_provider(chosen),
            notification_provider=context.monitoring.notification_provider,
        )

    trial = load_trial("trial_supported").model_copy(
        update={"trial_id": payload.trial_id}
    )
    seeded: list[dict] = []

    for patient_id, trajectory in COHORT:
        patient = load_patient("patient_eligible").model_copy(
            update={"patient_id": patient_id}
        )
        screening = screening_service.screen(patient, trial)

        existing = context.repository.list_treatments(
            trial_id=payload.trial_id, patient_id=patient_id
        )
        if existing:
            # Idempotent: re-seeding must not create a second active course.
            seeded.append(
                {
                    "patient_id": patient_id,
                    "trajectory": trajectory.value,
                    "skipped": "treatment already registered",
                }
            )
            continue

        treatment = context.treatment.register(
            screening_result_id=screening.result_id,
            drug_name="Compound X",
            now=start,
        )
        context.treatment.record_dose(
            treatment.treatment_id, amount=5.0, unit="mg", now=start
        )

        levels: list[str] = []
        for batch in generate_windowed(
            patient_id,
            payload.trial_id,
            trajectory,
            start,
            windows=payload.windows,
            hours=payload.hours,
            interval_minutes=payload.interval_minutes,
            seed=payload.seed,
        ):
            at = max(o.recorded_at for o in batch)
            context.ingestion.ingest(batch, now=at)
            cycle = context.monitoring.run_cycle(patient_id, payload.trial_id, at)
            levels.append(cycle.effective_risk.level.value)

        seeded.append(
            {
                "patient_id": patient_id,
                "trajectory": trajectory.value,
                "screening_status": screening.overall_status.value,
                "treatment_id": treatment.treatment_id,
                "risk_progression": levels,
            }
        )

    return {
        "trial_id": payload.trial_id,
        "seed": payload.seed,
        "synthetic": True,
        "risk_provider": context.monitoring.risk_provider.name,
        "model_version": context.monitoring.risk_provider.version,
        "note": "Synthetic demonstration data. Not clinical data.",
        "patients": seeded,
    }


# -- model provenance ------------------------------------------------------


@router.get("/model")
def get_model(request: Request) -> dict:
    """What produced the risk verdicts this deployment is serving.

    Every assessment already carries `provider` and `model_version`; this is the
    same provenance one level up, so a reviewer can see which artifact is
    loaded without opening a stored cycle.
    """
    provider = _context(request).monitoring.risk_provider
    payload: dict = {
        "provider": provider.name,
        "model_version": provider.version,
        "live_inference": provider.name == "synthetic_ml",
    }

    engine = getattr(provider, "_engine", None)
    if engine is None:
        return payload

    try:
        metadata = engine.metadata
    except Exception as exc:  # noqa: BLE001 - provenance must not break a page
        payload["artifact_error"] = str(exc)
        return payload

    payload["artifact"] = {
        "model_version": metadata.get("model_version"),
        "feature_version": metadata.get("feature_version"),
        "features": metadata.get("features", {}).get("names"),
        "estimator": metadata.get("estimator"),
        "training_cohort": metadata.get("training_cohort"),
        "scoring": metadata.get("scoring"),
        "created_at": metadata.get("created_at"),
        "model_sha256": metadata.get("model_sha256"),
        "trained_with": metadata.get("environment"),
    }
    return payload
