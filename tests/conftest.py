from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.db.models import Base
from app.db.session import get_session
from app.main import app

# ── Postgres container (started once per session) ─────────────────────────────

@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(postgres_container) -> str:
    host = postgres_container.get_container_host_ip()
    port = postgres_container.get_exposed_port(5432)
    user = postgres_container.username
    password = postgres_container.password
    db = postgres_container.dbname
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session")
def setup_schema(db_url: str):
    """Create schema once, synchronously — avoids session-loop vs test-loop issues."""
    async def _create():
        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_create())
    yield

    async def _drop():
        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_drop())


@pytest.fixture(autouse=True)
def clean_db(setup_schema, db_url: str):
    """TRUNCATE all tables after each test — sync fixture avoids loop-teardown issues."""
    yield
    async def _truncate():
        engine = create_async_engine(db_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(
                text("TRUNCATE task, task_run, task_context RESTART IDENTITY CASCADE")
            )
        await engine.dispose()
    asyncio.run(_truncate())


# ── Per-test engine + session + client ────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine(setup_schema, db_url: str):
    engine = create_async_engine(db_url, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
