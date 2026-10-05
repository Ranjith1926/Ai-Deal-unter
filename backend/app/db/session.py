"""Async SQLAlchemy engines and session factories."""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

_engine: AsyncEngine | None = None


def get_engine() -> AsyncEngine:
    """Shared pooled engine for the long-lived API process."""
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_pre_ping=True, pool_recycle=1800
        )
    return _engine


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def worker_session_factory(url: str | None = None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory for one background job.

    Celery runs each job in its own event loop, and pooled asyncpg connections cannot move
    between loops, so jobs use a pool-less engine that is disposed when the job ends.
    """
    engine = create_async_engine(url or get_settings().database_url, poolclass=NullPool)
    try:
        yield session_factory(engine)
    finally:
        await engine.dispose()
