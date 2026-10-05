"""Health endpoints.

  /health            quick "the process is up" answer (kept for compatibility)
  /health/live       liveness: the process responds. Never touches dependencies.
  /health/ready      readiness: database and Redis reachable (503 otherwise) - use for load balancers
  /health/database   database only          /health/redis   Redis only
  /health/providers  marketplace provider status. Always 200: one provider being down degrades
                     data freshness but must never make the application itself unavailable.
"""
import logging
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.db.session import get_engine
from app.providers.registry import provider_modes
from app.services import admin as admin_service
from app.services.common import utcnow

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=2)


def _ok(data: dict | None = None) -> dict:
    return {"success": True, "data": data or {"status": "ok"}, "message": None, "errors": []}


async def check_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis() -> None:
    client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
    try:
        await client.ping()
    finally:
        await client.aclose()


@router.get("")
async def health() -> dict:
    return _ok()


@router.get("/live")
async def live() -> dict:
    return _ok()


@router.get("/database")
async def health_database() -> dict:
    try:
        await check_database()
    except Exception:
        logger.exception("Database health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")
    return _ok()


@router.get("/redis")
async def health_redis() -> dict:
    try:
        await check_redis()
    except Exception:
        logger.exception("Redis health check failed")
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return _ok()


@router.get("/ready")
async def ready() -> dict:
    down = []
    for name, check in (("database", check_database), ("redis", check_redis)):
        try:
            await check()
        except Exception:
            logger.exception("Readiness check failed", extra={"dependency": name})
            down.append(name)
    if down:
        raise HTTPException(status_code=503, detail=f"Not ready: {', '.join(down)} unavailable")
    return _ok({"status": "ready"})


@router.get("/providers")
async def health_providers(session: SessionDep) -> dict:
    now = utcnow()
    modes = provider_modes()
    flags = await admin_service.provider_flags(session)
    rows = []
    for name in admin_service.PROVIDERS:
        last_ok, last_status = await admin_service.provider_last_runs(session, name)
        age = None if last_ok is None else (now - last_ok).total_seconds()
        if not flags[name]:
            state = "disabled"
        elif name not in modes:
            state = "unavailable"  # no usable integration configured
        elif last_status == "failed":
            state = "failing"
        elif last_ok is None or now - last_ok > STALE_AFTER:
            state = "stale"
        else:
            state = "healthy"
        rows.append({"name": name, "status": state, "enabled": flags[name], "demo_data": bool(modes.get(name)),
                     "last_success_at": last_ok, "last_success_age_seconds": None if age is None else round(age), "last_run_status": last_status})
    overall = "ok" if all(r["status"] in ("healthy", "disabled") for r in rows) else "degraded"
    return _ok({"status": overall, "providers": rows})
