"""Task Nexus context — context panel, entity attach/detach, suggestions."""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EntityPin, Task, TaskContext, TaskEntity
from app.db.session import get_session
from app.nexus import get_nexus_client
from app.templating import get_templates

router = APIRouter(tags=["context"])
Session = Annotated[AsyncSession, Depends(get_session)]
_TTL_DAYS = 7


# ── Auth helper ───────────────────────────────────────────────────────────────

def _request_user(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            return decoded.split(":", 1)[0] or "unknown"
        except Exception:
            pass
    return "unknown"


# ── Schemas ───────────────────────────────────────────────────────────────────

class AttachEntities(BaseModel):
    entity_names: list[str] = []
    entity_types: dict[str, str] = {}

    @field_validator("entity_names", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        """json-enc sends a bare string when only one checkbox is checked."""
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v or []


class DetachEntity(BaseModel):
    entity_name: str


# ── Shared helpers ────────────────────────────────────────────────────────────

def _query_text(task: Task) -> str:
    text = task.title
    if task.body:
        clean = " ".join(l for l in task.body.splitlines() if not l.startswith("["))
        if clean.strip():
            text += " " + clean.strip()[:300]
    return text


async def _get_attached(task_id: uuid.UUID, session: AsyncSession) -> list[TaskEntity]:
    """DB-only — fast, no LightRAG."""
    result = await session.execute(
        select(TaskEntity)
        .where(TaskEntity.task_id == task_id)
        .order_by(TaskEntity.source.desc(), TaskEntity.entity_name)
    )
    return list(result.scalars())


async def _render_fast_panel(
    request: Request, task_id: uuid.UUID, session: AsyncSession
) -> HTMLResponse:
    """Return entities panel with DB-only attached list.
    Suggestions are a lazy-loaded placeholder — browser fires them separately."""
    attached = await _get_attached(task_id, session)
    return get_templates().TemplateResponse(
        request,
        "_partials/entities_panel.html",
        {"task_id": str(task_id), "attached": attached},
    )


async def _build_suggestions(
    task: Task, session: AsyncSession
) -> list[dict]:
    """Slow path — calls LightRAG. Falls back to popular entities on error."""
    attached = await _get_attached(task.id, session)
    attached_names = {e.entity_name for e in attached}

    manual = [e for e in attached if e.source == "manual"]
    query = _query_text(task)
    if manual:
        query += " " + " ".join(e.entity_name for e in manual[:5])

    client = get_nexus_client()
    data = await client.query_context(query)
    raw = data.get("entities", [])[:15]

    if raw:
        return [
            {
                "name": e.get("entity_name", ""),
                "type": e.get("entity_type", ""),
                "description": e.get("description", ""),
            }
            for e in raw
            if e.get("entity_name") and e.get("entity_name") not in attached_names
        ][:10]

    # Fallback to popular entities
    popular = await client.popular_entities(limit=30)
    return [
        {"name": n, "type": "", "description": ""}
        for n in popular
        if n not in attached_names
    ][:10]


# ── Nexus context panel (task detail left column) ─────────────────────────────

async def _fetch_and_cache(task: Task, session: AsyncSession) -> list[dict]:
    client = get_nexus_client()
    data = await client.query_context(_query_text(task))
    raw = data.get("entities", [])[:8]
    entities = [
        {"name": e.get("entity_name",""), "type": e.get("entity_type",""), "description": e.get("description","")}
        for e in raw if e.get("entity_name")
    ]
    await session.execute(TaskContext.__table__.delete().where(
        and_(TaskContext.__table__.c.task_id == task.id, TaskContext.__table__.c.source == "nexus")
    ))
    session.add(TaskContext(task_id=task.id, source="nexus", snippet=json.dumps(entities), stale=False))
    await session.execute(TaskEntity.__table__.delete().where(
        and_(TaskEntity.__table__.c.task_id == task.id, TaskEntity.__table__.c.source == "auto")
    ))
    for i, e in enumerate(entities[:5]):
        session.add(TaskEntity(task_id=task.id, entity_name=e["name"], entity_type=e["type"] or None, source="auto", relevance=round(1.0 - i * 0.15, 2)))
    await session.commit()
    return entities


async def _pinned_names(session: AsyncSession) -> set[str]:
    result = await session.execute(select(EntityPin.entity_name))
    return {row[0] for row in result}


@router.get("/tasks/{task_id}/context", response_class=HTMLResponse)
async def get_task_context(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    cutoff = datetime.now(timezone.utc) - timedelta(days=_TTL_DAYS)
    result = await session.execute(
        select(TaskContext).where(and_(
            TaskContext.task_id == task_id, TaskContext.source == "nexus",
            TaskContext.stale == False, TaskContext.fetched_at > cutoff,  # noqa: E712
        )).order_by(TaskContext.fetched_at.desc()).limit(1)
    )
    cached = result.scalar_one_or_none()
    if cached:
        entities, fetched_at, from_cache = json.loads(cached.snippet), cached.fetched_at, True
    else:
        entities, fetched_at, from_cache = await _fetch_and_cache(task, session), datetime.now(timezone.utc), False
    return get_templates().TemplateResponse(request, "_partials/context_panel.html", {
        "task_id": str(task_id), "entities": entities, "fetched_at": fetched_at,
        "from_cache": from_cache, "pinned_names": await _pinned_names(session),
    })


@router.post("/tasks/{task_id}/context/refresh", response_class=HTMLResponse)
async def refresh_task_context(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    entities = await _fetch_and_cache(task, session)
    return get_templates().TemplateResponse(request, "_partials/context_panel.html", {
        "task_id": str(task_id), "entities": entities, "fetched_at": datetime.now(timezone.utc),
        "from_cache": False, "pinned_names": await _pinned_names(session),
    })


# ── Entities panel (right column) — fast path ─────────────────────────────────

@router.get("/tasks/{task_id}/entities-panel", response_class=HTMLResponse)
async def get_entities_panel(request: Request, task_id: uuid.UUID, session: Session):
    if not await session.get(Task, task_id):
        raise HTTPException(404, "Task not found")
    return await _render_fast_panel(request, task_id, session)


# ── Suggestions — slow path, called lazily by the panel ──────────────────────

@router.get("/tasks/{task_id}/entities-panel/suggestions", response_class=HTMLResponse)
async def get_entities_suggestions(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    suggestions = await _build_suggestions(task, session)
    return get_templates().TemplateResponse(
        request, "_partials/ep_suggestions_section.html",
        {"task_id": str(task_id), "suggestions": suggestions},
    )


# ── Live search within the panel ─────────────────────────────────────────────

@router.get("/tasks/{task_id}/entities-panel/search", response_class=HTMLResponse)
async def search_entities_for_panel(
    request: Request, task_id: uuid.UUID, session: Session, q: str = ""
):
    templates = get_templates()

    # When cleared, fall back to popular (fast — no LightRAG query)
    if not q or len(q.strip()) < 2:
        result = await session.execute(select(TaskEntity.entity_name).where(TaskEntity.task_id == task_id))
        attached_names = {row[0] for row in result}
        popular = await get_nexus_client().popular_entities(limit=20)
        suggestions = [{"name": n, "type": "", "description": ""} for n in popular if n not in attached_names][:10]
        return templates.TemplateResponse(request, "_partials/ep_suggest_content.html",
            {"suggestions": suggestions, "task_id": str(task_id), "searching": False})

    names = await get_nexus_client().search_entities(q.strip(), limit=15)
    result = await session.execute(select(TaskEntity.entity_name).where(TaskEntity.task_id == task_id))
    attached_names = {row[0] for row in result}
    names = [n for n in names if n not in attached_names]
    suggestions = [{"name": n, "type": "", "description": ""} for n in names]
    return templates.TemplateResponse(request, "_partials/ep_suggest_content.html",
        {"suggestions": suggestions, "task_id": str(task_id), "searching": True, "q": q})


# ── Attach / detach — both return the fast panel immediately ─────────────────

@router.post("/tasks/{task_id}/entities/attach", response_class=HTMLResponse)
async def attach_entities(
    request: Request, task_id: uuid.UUID, data: AttachEntities, session: Session
):
    if not await session.get(Task, task_id):
        raise HTTPException(404, "Task not found")
    actor = _request_user(request)
    now = datetime.now(timezone.utc)
    for name in data.entity_names:
        name = name.strip()
        if not name:
            continue
        existing = await session.execute(
            select(TaskEntity).where(and_(TaskEntity.task_id == task_id, TaskEntity.entity_name == name))
        )
        if not existing.scalar_one_or_none():
            etype = (data.entity_types.get(name) or "").strip() or None
            session.add(TaskEntity(task_id=task_id, entity_name=name, entity_type=etype,
                                   source="manual", relevance=1.0, attached_by=actor, attached_at=now))
    await session.commit()
    return await _render_fast_panel(request, task_id, session)


@router.post("/tasks/{task_id}/entities/detach", response_class=HTMLResponse)
async def detach_entity(
    request: Request, task_id: uuid.UUID, data: DetachEntity, session: Session
):
    if not await session.get(Task, task_id):
        raise HTTPException(404, "Task not found")
    await session.execute(TaskEntity.__table__.delete().where(
        and_(TaskEntity.__table__.c.task_id == task_id, TaskEntity.__table__.c.entity_name == data.entity_name)
    ))
    await session.commit()
    return await _render_fast_panel(request, task_id, session)
