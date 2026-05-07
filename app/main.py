from __future__ import annotations

import base64
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import models  # noqa: F401 — registers mappers before alembic runs
from app.routes import api, context, entities, tasks, webhooks

APP_DIR = Path(__file__).parent

# Paths that skip Basic Auth
_PUBLIC_PATHS = {"/healthz"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Scout HQ",
    description="Personal cockpit for 1st Beetley Scout Group GLV",
    version="0.2.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Basic "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": 'Basic realm="Scout HQ"'},
        )

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials"},
            headers={"WWW-Authenticate": 'Basic realm="Scout HQ"'},
        )

    ok = secrets.compare_digest(username, settings.scouthq_username) and secrets.compare_digest(
        password, settings.scouthq_password
    )
    if not ok:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials"},
            headers={"WWW-Authenticate": 'Basic realm="Scout HQ"'},
        )

    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

app.include_router(tasks.router)
app.include_router(webhooks.router)
app.include_router(context.router)
app.include_router(entities.router)
app.include_router(api.router)


@app.get("/healthz", tags=["ops"])
async def healthz():
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal
    from app.nexus import get_nexus_client

    db_status = "ok"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    nexus_ok = await get_nexus_client().health()

    return {"db": db_status, "nexus": "ok" if nexus_ok else "degraded"}
