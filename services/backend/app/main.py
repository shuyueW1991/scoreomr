"""FastAPI application factory.

Run with ``uvicorn app.main:create_app --factory``.  A factory keeps test
imports side-effect free and makes it impossible to boot with two different
configurations in one process.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .auth import ANON_COOKIE, ANON_MAX_AGE
from .config import Settings
from .context import AppContext
from .errors import DomainError
from .routes import jobs as job_routes
from .routes import public as public_routes

log = logging.getLogger(__name__)


def _error_response(status: int, code: str, message: str, *, extra: dict | None = None, headers: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if extra:
        body["error"].update(extra)
    return JSONResponse(body, status_code=status, headers=headers or {})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    ctx = AppContext.build(settings)
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "ScoreOMR %s starting env=%s omr_mock=%s",
            __version__, settings.app_env, settings.omr_mock,
        )
        yield

    docs = None if settings.is_production else "/api/docs"
    openapi = None if settings.is_production else "/api/openapi.json"
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="Score screenshot -> MusicXML / MIDI / WAV.",
        docs_url=docs,
        redoc_url=None,
        openapi_url=openapi,
        lifespan=lifespan,
    )
    app.state.ctx = ctx

    @app.middleware("http")
    async def api_headers(request: Request, call_next):
        path = request.url.path
        response = await call_next(request)

        state_anon = getattr(request.state, "anon_id", None)
        cookie_anon = request.cookies.get(ANON_COOKIE)
        if (
            path.startswith("/api/")
            and state_anon
            and state_anon != cookie_anon
        ):
            response.set_cookie(
                ANON_COOKIE,
                state_anon,
                max_age=ANON_MAX_AGE,
                httponly=True,
                samesite="lax",
                secure=settings.cookies_secure,
                path="/",
            )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        headers: dict[str, str] = {}
        if "retry_after" in exc.extra:
            headers["Retry-After"] = str(exc.extra.pop("retry_after"))
        return _error_response(exc.status_code, exc.code, exc.message, extra=exc.extra, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            if loc:
                fields.append(loc)
        return _error_response(
            422, "validation_error", "请求参数不合法", extra={"fields": fields} if fields else None
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        if exc.status_code == 404:
            message = "接口或资源不存在"
        return _error_response(exc.status_code, "http_error", str(message))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _error_response(500, "internal_error", "服务器内部错误，请稍后重试")

    app.include_router(public_routes.router)
    app.include_router(job_routes.router)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "service": settings.app_name,
            "version": __version__,
            "health": "/api/health",
            "docs": docs,
        }

    return app