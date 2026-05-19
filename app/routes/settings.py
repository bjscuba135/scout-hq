"""Settings — agent configuration."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.templating import get_templates

router = APIRouter(prefix="/settings", tags=["settings"])
templates = get_templates()

_KIND_MAP = {
    "human":       "human",
    "claude_code": "code",
    "n8n_webhook": "pipe",
    "openclaw":    "comms",
}


@router.get("", response_class=HTMLResponse)
async def settings_redirect(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/settings/agents")


@router.get("/agents", response_class=HTMLResponse)
async def settings_agents(request: Request):
    cfg = get_settings()
    raw = cfg.load_dispatchers()
    dispatchers = raw.get("dispatchers", []) if isinstance(raw, dict) else []
    agents = []
    for d in dispatchers:
        agents.append({
            "id":   d.get("owner_pattern", d.get("type", "?")),
            "name": d.get("name", d.get("type", "?")),
            "kind": _KIND_MAP.get(d.get("type", ""), "pipe"),
            "raw":  d,
        })

    ctx = {
        "agents": agents,
        "selected": agents[0] if agents else None,
        "active_nav": "settings",
    }
    return templates.TemplateResponse(request, "settings/agents.html", ctx)
