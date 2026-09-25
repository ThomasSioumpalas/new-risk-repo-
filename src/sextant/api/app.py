"""FastAPI application factory."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from sextant import ENGINE_VERSION, __version__
from sextant.api.routers import insight, register, workflow
from sextant.config import Settings, get_settings
from sextant.db.session import make_engine, make_session_factory
from sextant.engine.model import ModelError
from sextant.engine.simulation import SimulationTooLargeError
from sextant.observability import configure_logging, get_logger
from sextant.services.errors import (
    ConflictError,
    DomainError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
)

_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    PermissionDeniedError: 403,
    ConflictError: 409,
    InvalidRequestError: 422,
}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

DESCRIPTION = """
Quantitative, auditable information-security risk register.

* **Risk assessment**: FAIR-aligned Monte Carlo with explicit uncertainty; ISO/IEC 27005 / NIST SP 800-30 matrix.
* **Governance**: immutable assessments, justified overrides, authority matrix, segregation of duties,
  time-limited acceptance, hash-chained audit log.
* **Compliance**: control mapping and readiness indicators. These are **not** a certification or an audit opinion.

Authenticate with the `X-API-Key` header.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log = get_logger("sextant.api")
    engine = make_engine(settings.database_url)

    app = FastAPI(title="Sextant", version=__version__, description=DESCRIPTION)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        log.info(
            "request",
            method=request.method,
            route=getattr(route, "path", request.url.path),
            status=response.status_code,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=_STATUS.get(type(exc), 400), content={"error": exc.code, "message": str(exc)}
        )

    @app.exception_handler(ModelError)
    async def model_error(_: Request, exc: ModelError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "model_error", "message": str(exc)})

    @app.exception_handler(SimulationTooLargeError)
    async def too_large(_: Request, exc: SimulationTooLargeError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": "simulation_too_large", "message": str(exc)})

    @app.exception_handler(ValidationError)
    async def validation_error(_: Request, exc: ValidationError) -> JSONResponse:
        # Raised when stored or derived data fails domain validation inside a service.
        return JSONResponse(
            status_code=422, content={"error": "validation_error", "message": exc.errors(include_url=False)}
        )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/version", tags=["system"])
    def version() -> dict[str, str]:
        return {"version": __version__, "engine_version": ENGINE_VERSION}

    app.include_router(register.router)
    app.include_router(workflow.router)
    app.include_router(insight.router)
    return app


def __getattr__(name: str) -> FastAPI:
    """Lazily create the module-level ``app`` for ``uvicorn sextant.api.app:app``."""
    if name == "app":
        return create_app()
    raise AttributeError(name)
