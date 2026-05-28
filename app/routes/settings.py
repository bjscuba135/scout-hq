"""Settings — agent configuration."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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
_VALID_SECTIONS = {"agents", "tokens", "policy", "nexus"}


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _settings_context(selected_id: str | None = None, section: str = "agents") -> dict:
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

    selected = next((agent for agent in agents if agent["id"] == selected_id), None)
    if section == "agents" and selected is None and agents:
        selected = agents[0]

    return {
        "agents": agents,
        "selected": selected,
        "selected_section": section,
        "active_nav": "settings",
    }


@router.get("", response_class=HTMLResponse)
async def settings_redirect(request: Request):
    return RedirectResponse("/settings/agents")


@router.get("/{section}", response_class=HTMLResponse)
async def settings_section(request: Request, section: str, selected: str | None = None):
    if section not in _VALID_SECTIONS:
        return RedirectResponse("/settings/agents")

    ctx = _settings_context(selected_id=selected, section=section)
    if _is_htmx(request) and request.headers.get("HX-Target") == "nx-settings-config":
        return templates.TemplateResponse(request, "settings/_config.html", ctx)
    if _is_htmx(request) and request.headers.get("HX-Target") == "":
        # Defensive: never swap a whole settings page into an inner panel.
        return templates.TemplateResponse(request, "settings/_config.html", ctx)
    return templates.TemplateResponse(request, "settings/agents.html", ctx)
