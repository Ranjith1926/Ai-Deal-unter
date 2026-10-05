"""FastAPI entrypoint."""
import hmac
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import health
from app.api.deps import SessionDep
from app.api.routes import account, admin, assistant, auth, catalog
from app.core import metrics
from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError, UnauthorizedError
from app.core.hardening import BodySizeLimitMiddleware, production_problems
from app.core.logging import configure_logging, correlation_id
from app.providers.registry import provider_modes

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
access_log = logging.getLogger("app.access")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start a production deployment with unsafe settings, and say exactly what to fix.
    problems = production_problems(settings)
    if problems:
        for p in problems:
            logger.critical("Unsafe production configuration: %s", p)
        raise RuntimeError("Refusing to start: " + "; ".join(problems))
    # One shared client for rate limiting and response caching. Redis being down at startup is
    # not fatal: both features fail open.
    app.state.redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        yield
    finally:
        await app.state.redis.aclose()


# API docs describe every endpoint; they are for development, not for the public internet.
_docs = not settings.is_production
app = FastAPI(
    title="AI Deal Hunter API", version="1.0.0", lifespan=lifespan,
    docs_url="/docs" if _docs else None, redoc_url=None, openapi_url="/openapi.json" if _docs else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Retry-After"],
)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)

_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
_QUIET_PATHS = ("/health/live", "/health/ready", "/metrics")


@app.middleware("http")
async def observe_and_secure(request: Request, call_next):
    cid = (request.headers.get("X-Request-ID") or uuid.uuid4().hex)[:100]
    correlation_id.set(cid)
    started = time.perf_counter()
    metrics.HTTP_IN_FLIGHT.inc()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
    finally:
        metrics.HTTP_IN_FLIGHT.dec()
        elapsed = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", None) or "unmatched"  # template, never the raw URL
        if request.url.path not in _QUIET_PATHS:
            metrics.observe_request(request.method, route, status, elapsed)
            access_log.info("request", extra={"method": request.method, "route": route, "status": status, "duration_ms": round(elapsed * 1000, 1)})
    response.headers["X-Request-ID"] = cid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-site"
    if not request.url.path.startswith(_DOC_PATHS):  # Swagger UI needs its own scripts
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _envelope(message: str, errors: list[str], status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status, headers=headers,
        content={"success": False, "data": None, "message": message, "errors": errors},
    )


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return _envelope(exc.message, exc.errors, exc.status_code, exc.headers)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _envelope(str(exc.detail), [], exc.status_code, getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [f"{'.'.join(str(p) for p in e['loc'][1:]) or e['loc'][0]}: {e['msg']}" for e in exc.errors()]
    return _envelope("Validation failed", errors, 422)


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error")  # details stay in the logs; the client gets nothing internal
    return _envelope("Internal server error", [], 500)


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request, session: SessionDep) -> Response:
    """Prometheus scrape endpoint. Needs METRICS_TOKEN in production; off entirely there if unset."""
    token = settings.metrics_token
    if token:
        supplied = request.headers.get("authorization", "")[7:] if request.headers.get("authorization", "").lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise UnauthorizedError("Invalid metrics token")
    elif settings.is_production:
        raise NotFoundError("Not found")
    await metrics.refresh_business_gauges(session, provider_modes())
    body, content_type = metrics.render()
    return Response(body, media_type=content_type)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(account.router)
app.include_router(assistant.router)
app.include_router(admin.router)
