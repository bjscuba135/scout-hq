from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db.session import engine
from app.db import models  # noqa: F401 — registers mappers before alembic runs
from app.routes import tasks, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Nothing to do on startup beyond Alembic (run via CMD in Dockerfile).
    # Keep hook here for Phase 2+ (Nexus client init, file watcher start).
    yield


app = FastAPI(
    title="Scout HQ",
    description="Personal cockpit for 1st Beetley Scout Group GLV",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(tasks.router)
app.include_router(webhooks.router)


@app.get("/healthz", tags=["ops"])
async def healthz():
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    db_status = "ok"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return {"db": db_status, "nexus": "degraded"}  # nexus wired in Phase 2
