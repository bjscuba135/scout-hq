"""Agent status — dispatcher cards and recent run history."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import TaskRun
from app.db.session import get_session
from app.templating import get_templates

router = APIRouter(prefix="/agents", tags=["agents"])
templates = get_templates()

Session = Annotated[AsyncSession, Depends(get_session)]

# Kind labels for the UI
_KIND_MAP = {
    "human":       {"label": "Human",        "kind": "human"},
    "claude_code": {"label": "Claude Code",  "kind": "code"},
    "n8n_webhook": {"label": "n8n",          "kind": "pipe"},
    "openclaw":    {"label": "OpenClaw",     "kind": "comms"},
}


def _dispatchers_to_agents(dispatchers: list[dict]) -> list[dict]:
    agents = []
    for d in dispatchers:
        kind_meta = _KIND_MAP.get(d.get("type", ""), {"label": d.get("type", "?"), "kind": "pipe"})
        agents.append({
            "id":    d.get("owner_pattern", d.get("type", "?")),
            "name":  d.get("name", kind_meta["label"]),
            "kind":  kind_meta["kind"],
            "type":  d.get("type"),
            "desc":  d.get("desc", ""),
            "status": "idle",
        })
    # Always include the human dispatcher
    if not any(a["kind"] == "human" for a in agents):
        agents.insert(0, {"id": "ben", "name": "Ben (Human)", "kind": "human",
                          "type": "human", "desc": "Final approver.", "status": "idle"})
    return agents


@router.get("", response_class=HTMLResponse)
async def agents_page(request: Request, session: Session):
    settings = get_settings()
    raw = settings.load_dispatchers()
    dispatchers = raw.get("dispatchers", []) if isinstance(raw, dict) else []
    agents = _dispatchers_to_agents(dispatchers)

    runs_result = await session.execute(
        select(TaskRun).order_by(TaskRun.started_at.desc()).limit(30)
    )
    runs = runs_result.scalars().all()

    ctx = {"agents": agents, "runs": runs}
    return templates.TemplateResponse(request, "agents/list.html", ctx)


@router.get("/pulse", response_class=HTMLResponse)
async def agents_pulse(request: Request, session: Session):
    """HTMX polling target — returns a small status card fragment."""
    runs_result = await session.execute(
        select(TaskRun).order_by(TaskRun.started_at.desc()).limit(5)
    )
    runs = runs_result.scalars().all()
    return templates.TemplateResponse(request, "agents/_pulse.html", {"runs": runs})
