"""HTTP routes.

The important structural point: `/screen/pdf` parses bytes into canonical
models and then calls the *same* `service.screen()` that `/screen` calls. It
contains no screening logic. Every future input adapter (LLM extraction, OCR,
CSV, EMR API) joins at exactly that line.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from .models import (
    ErrorResponse,
    HealthResponse,
    RecordReviewRequest,
    ScreenRequest,
)
from ..extraction.errors import ExtractionError
from ..extraction.parser import parse_document
from ..repository.base import RepositoryError
from ..schema.result import ScreeningResult
from ..service import ReviewError, ScreeningService

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

_ERRORS = {
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _service(request: Request) -> ScreeningService:
    return request.app.state.service


def _fail(status: int, code: str, message: str, details: list[str] | None = None):
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": message, "details": details or []},
    )


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    service = _service(request)
    return HealthResponse(
        status="ok",
        phase="1",
        ai_provider=service.ai_provider.name,
        repository=type(service.repository).__name__,
    )


@router.post("/screen", response_model=ScreeningResult, responses=_ERRORS)
def screen(request: Request, payload: ScreenRequest) -> ScreeningResult:
    """Screen a canonical Patient against a canonical Trial."""
    try:
        return _service(request).screen(payload.patient, payload.trial)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The screening result could not be saved.", [str(exc)])


@router.post("/screen/pdf", response_model=ScreeningResult, responses=_ERRORS)
async def screen_pdf(
    request: Request, file: UploadFile = File(...)
) -> ScreeningResult:
    """Adapter: structured PDF -> canonical models -> the same screening service."""
    data = await file.read()

    if len(data) > MAX_UPLOAD_BYTES:
        _fail(
            422,
            "FILE_TOO_LARGE",
            f"The file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    try:
        patient, trial = parse_document(data)
    except ExtractionError as exc:
        _fail(422, exc.code, exc.message, exc.details)

    try:
        return _service(request).screen(patient, trial)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The screening result could not be saved.", [str(exc)])


@router.get("/results", response_model=list[ScreeningResult], responses=_ERRORS)
def list_results(request: Request) -> list[ScreeningResult]:
    try:
        return _service(request).list_results()
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Stored results could not be read.", [str(exc)])


@router.get("/results/{result_id}", response_model=ScreeningResult, responses={404: {"model": ErrorResponse}, **_ERRORS})
def get_result(request: Request, result_id: str) -> ScreeningResult:
    try:
        result = _service(request).get_result(result_id)
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "Stored results could not be read.", [str(exc)])
    if result is None:
        _fail(404, "RESULT_NOT_FOUND", f"No screening result with id '{result_id}'.")
    return result


@router.post(
    "/results/{result_id}/review",
    response_model=ScreeningResult,
    responses={404: {"model": ErrorResponse}, **_ERRORS},
)
def record_review(
    request: Request, result_id: str, payload: RecordReviewRequest
) -> ScreeningResult:
    """Record a human decision about a screening.

    Returns the same `ScreeningResult` with `review` populated. Every
    deterministic field is unchanged — the review is stored beside the verdict,
    never over it.
    """
    try:
        return _service(request).record_review(
            result_id=result_id,
            decision=payload.decision,
            reviewer=payload.reviewer,
            note=payload.note,
            now=payload.now,
        )
    except ReviewError as exc:
        _fail(
            404 if exc.code == "RESULT_NOT_FOUND" else 422,
            exc.code,
            exc.message,
            exc.details,
        )
    except RepositoryError as exc:
        _fail(503, "PERSISTENCE_FAILED", "The review could not be saved.", [str(exc)])
