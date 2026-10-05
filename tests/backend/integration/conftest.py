"""Integration fixtures: a throwaway Postgres database (and Redis db 15), skipped if unreachable."""
import argparse
import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import session_factory
from app.engine.config import ScoringConfig

BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"


def _urls() -> tuple[str, str, str]:
    base = make_url(os.getenv("TEST_DATABASE_URL") or get_settings().database_url)
    test_db = base.database if base.database.endswith("_test") else f"{base.database}_test"
    return (
        base.set(database="postgres").render_as_string(hide_password=False),
        base.set(database=test_db).render_as_string(hide_password=False),
        test_db,
    )


@pytest.fixture(scope="session")
def test_db_url() -> str:
    admin_url, url, name = _urls()

    async def recreate() -> None:
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
        finally:
            await engine.dispose()

    try:
        asyncio.run(recreate())
    except Exception as exc:  # no Postgres reachable (e.g. running tests on the host)
        pytest.skip(f"PostgreSQL not reachable for integration tests: {type(exc).__name__}")

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.cmd_opts = argparse.Namespace(x=[f"db_url={url}"])
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
async def factory(test_db_url):
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield session_factory(engine)
    await engine.dispose()


@pytest.fixture
def config() -> ScoringConfig:
    return ScoringConfig()


@pytest.fixture
async def client(factory):
    """HTTP client against the real app, wired to the throwaway test database."""
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_scoring_config, get_session
    from app.main import app

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_scoring_config] = lambda: ScoringConfig()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    if hasattr(app.state, "redis"):
        del app.state.redis


@pytest.fixture
async def world(factory, config):
    from helpers import build_world

    return await build_world(factory, config)


@pytest.fixture
def redis_url() -> str:
    import redis as redis_sync

    url = get_settings().redis_url.rsplit("/", 1)[0] + "/15"
    client = redis_sync.Redis.from_url(url, socket_connect_timeout=2)
    try:
        client.flushdb()
    except Exception:
        pytest.skip("Redis not reachable for integration tests")
    finally:
        client.close()
    return url
