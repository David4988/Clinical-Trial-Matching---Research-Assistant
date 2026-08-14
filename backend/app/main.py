"""FastAPI application.

Run:  uvicorn app.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .service import ScreeningService

logger = logging.getLogger("clinical-screening")

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def create_app(service: ScreeningService | None = None) -> FastAPI:
    app = FastAPI(
        title="Clinical Trial Matching & Research Assistant",
        description=(
            "Phase 1. Deterministic rules are authoritative; heuristics and the "
            "mock AI layer are advisory and cannot change an eligibility verdict."
        ),
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.state.service = service or ScreeningService()
    app.include_router(router)

    # Every failure leaves through one of these three handlers, so the client
    # always receives {"error": {code, message, details}} and never a traceback.

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = detail
        else:
            body = {"code": f"HTTP_{exc.status_code}", "message": str(detail), "details": []}
        return JSONResponse(status_code=exc.status_code, content={"error": body})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request, exc: RequestValidationError):
        details = [
            f"{'.'.join(str(p) for p in err.get('loc', ()))}: {err.get('msg', '')}".strip(": ")
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "The request body does not match the canonical schema.",
                    "details": details[:20],
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred while processing the request.",
                    "details": [],
                }
            },
        )

    return app


app = create_app()
