"""FastAPI dependencies: DB session, authentication, scoring config, rate limiting."""
import logging
import time
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, AsyncIterator

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.errors import ForbiddenError, RateLimitedError, UnauthorizedError
from app.core.hardening import client_ip as _client_ip
from app.core.hardening import hash_subject
from app.core.security import decode_access_token
from app.db.session import get_engine, session_factory
from app.engine.config import ScoringConfig
from app.models import User
from app.services.catalog_query import SORTS, ProductFilter
from app.services.common import load_scoring_config

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


@lru_cache
def _sessionmaker() -> async_sessionmaker[AsyncSession]:
    return session_factory(get_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _sessionmaker()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]

# --------------------------------------------------------------------- scoring config
_config_cache: tuple[float, ScoringConfig] | None = None
CONFIG_TTL_SECONDS = 60


async def get_scoring_config() -> ScoringConfig:
    """Defaults plus admin overrides, cached briefly so requests don't re-read settings."""
    global _config_cache
    if _config_cache and time.monotonic() - _config_cache[0] < CONFIG_TTL_SECONDS:
        return _config_cache[1]
    config = await load_scoring_config(_sessionmaker())
    _config_cache = (time.monotonic(), config)
    return config


ConfigDep = Annotated[ScoringConfig, Depends(get_scoring_config)]


# --------------------------------------------------------------------- authentication
async def optional_user(
    session: SessionDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None
) -> User | None:
    """None when no token is sent; 401 when a token is sent but invalid."""
    if creds is None:
        return None
    user = await session.get(User, decode_access_token(creds.credentials))
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid access token")
    return user


async def current_user(user: Annotated[User | None, Depends(optional_user)]) -> User:
    if user is None:
        raise UnauthorizedError()
    return user


async def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise ForbiddenError("Administrator access required")
    return user


UserDep = Annotated[User, Depends(current_user)]
OptionalUserDep = Annotated[User | None, Depends(optional_user)]
AdminDep = Annotated[User, Depends(admin_user)]


# --------------------------------------------------------------------- rate limiting
def client_ip(request: Request) -> str:
    """Caller address for rate limiting. X-Forwarded-For is honoured only for the configured number of trusted proxies."""
    return _client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        get_settings().trusted_proxy_count,
    )


_now = time.time  # indirection so tests can pin the clock


async def hit_limit(request: Request, name: str, subject: str, limit: int, window: int) -> None:
    """Count one request against a fixed window in Redis. Fails open: a Redis outage must not take the API down."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    now = _now()
    key = f"dh:rl:{name}:{subject}:{int(now // window)}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window + 1)
    except RedisError:
        logger.warning("Rate limiter unavailable; allowing request")
        return
    if count > limit:
        raise RateLimitedError(retry_after=max(1, int(window - now % window)))


def rate_limit(name: str, per_minute_setting: str):
    """Per-client-IP limit, in requests per minute (the setting's value)."""

    async def dependency(request: Request) -> None:
        await hit_limit(request, name, client_ip(request), getattr(get_settings(), per_minute_setting), 60)

    return dependency


class LoginGuard:
    """Throttles failed sign-ins per account+IP, and per account from anywhere (slower credential stuffing).

    Counts only failures, so legitimate users are never slowed down. Fails open if Redis is unavailable.
    """

    def __init__(self, request: Request, email: str) -> None:
        self.request, self.email = request, email
        s = get_settings()
        self.limit, self.window = s.login_failure_limit, s.login_failure_window_seconds
        subject = hash_subject(email)
        self.keys = [(f"dh:lf:{subject}:{hash_subject(client_ip(request))}", self.limit), (f"dh:lf:{subject}", self.limit * 4)]

    async def check(self) -> None:
        redis = getattr(self.request.app.state, "redis", None)
        if redis is None:
            return
        try:
            for key, limit in self.keys:
                count = await redis.get(key)
                if count is not None and int(count) >= limit:
                    ttl = await redis.ttl(key)
                    raise RateLimitedError(retry_after=max(1, int(ttl)) if ttl and ttl > 0 else self.window)
        except RedisError:
            logger.warning("Login throttle unavailable; allowing attempt")

    async def failed(self) -> None:
        redis = getattr(self.request.app.state, "redis", None)
        if redis is None:
            return
        try:
            for key, _ in self.keys:
                if await redis.incr(key) == 1:
                    await redis.expire(key, self.window)
        except RedisError:
            logger.warning("Login throttle unavailable; failure not counted")

    async def succeeded(self) -> None:
        redis = getattr(self.request.app.state, "redis", None)
        if redis is not None:
            try:
                await redis.delete(self.keys[0][0])  # forgive this IP; the per-account counter keeps running
            except RedisError:
                pass


async def raw_token(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None) -> str | None:
    """The caller's bearer token, for passing through to services that act on their behalf."""
    return creds.credentials if creds else None


GeneralLimit = Depends(rate_limit("api", "rate_limit_per_minute"))
AuthLimit = Depends(rate_limit("auth", "auth_rate_limit_per_minute"))


# --------------------------------------------------------------------- shared query params
def product_filter(
    q: Annotated[str | None, Query(max_length=200)] = None,
    category: Annotated[str | None, Query(max_length=140)] = None,
    brand: Annotated[str | None, Query(max_length=120)] = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    platform: Annotated[str | None, Query(max_length=32)] = None,
    deal_score: Annotated[float | None, Query(ge=0, le=100, description="Minimum deal score")] = None,
    value_score: Annotated[float | None, Query(ge=0, le=100, description="Minimum value score")] = None,
) -> ProductFilter:
    return ProductFilter(
        q=q, category=category, brand=brand, min_price=min_price, max_price=max_price,
        platform=platform, min_deal_score=deal_score, min_value_score=value_score,
    )


FilterDep = Annotated[ProductFilter, Depends(product_filter)]
SortParam = Annotated[str, Query(description=f"One of: {', '.join(SORTS)}")]
PageParam = Annotated[int, Query(ge=1, le=10_000)]
PageSizeParam = Annotated[int, Query(ge=1, le=100)]
