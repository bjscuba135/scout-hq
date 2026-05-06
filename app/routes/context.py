"""Task Nexus context — fetch, cache, refresh, and entity attach/detach."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EntityPin, Task, TaskContext, TaskEntity
from app.db.session import get_session
from app.nexus import get_nexus_client
from app.templating import get_templates

router = APIRouter(tags=["context"])
Session = Annotated[AsyncSession, Depends(get_session)]


# ── Schemas ───────────────────────────────────────────────────────────────────

class AttachEntities(BaseModel):
    entity_names: list[str] = []

class DetachEntity(BaseModel):
    entity_name: str

_TTL_DAYS = 7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _query_text(task: Task) -> str:
    """Build a LightRAG query string from a task."""
    text = task.title
    if task.body:
        # Skip timestamped note lines — they add noise, not signal
        clean = " ".join(
            line for line in task.body.splitlines()
            if not line.startswith("[")
        )
        if clean.strip():
            text += " " + clean.strip()[:300]
    return text


async def _fetch_and_cache(task: Task, session: AsyncSession) -> list[dict]:
    """Query LightRAG, persist to task_context + task_entity, return entity list."""
    client = get_nexus_client()
    data = await client.query_context(_query_text(task))
    raw = data.get("entities", [])[:8]

    entities = [
        {
            "name": e.get("entity_name", ""),
            "type": e.get("entity_type", ""),
            "description": e.get("description", ""),
        }
        for e in raw
        if e.get("entity_name")
    ]

    # Replace any existing nexus context row for this task
    await session.execute(
        TaskContext.__table__.delete().where(
            and_(
                TaskContext.__table__.c.task_id == task.id,
                TaskContext.__table__.c.source == "nexus",
            )
        )
    )
    session.add(
        TaskContext(
            task_id=task.id,
            source="nexus",
            snippet=json.dumps(entities),
            stale=False,
        )
    )

    # Refresh auto task→entity links (top 5)
    await session.execute(
        TaskEntity.__table__.delete().where(
            and_(
                TaskEntity.__table__.c.task_id == task.id,
                TaskEntity.__table__.c.source == "auto",
            )
        )
    )
    for i, e in enumerate(entities[:5]):
        session.add(
            TaskEntity(
                task_id=task.id,
                entity_name=e["name"],
                entity_type=e["type"] or None,
                source="auto",
                relevance=round(1.0 - i * 0.15, 2),
            )
        )

    await session.commit()
    return entities


async def _pinned_names(session: AsyncSession) -> set[str]:
    result = await session.execute(select(EntityPin.entity_name))
    return {row[0] for row in result}


async def _render_panel(
    request: Request,
    task_id: uuid.UUID,
    entities: list[dict],
    fetched_at: datetime,
    from_cache: bool,
    session: AsyncSession,
) -> HTMLResponse:
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "_partials/context_panel.html",
        {
            "task_id": str(task_id),
            "entities": entities,
            "fetched_at": fetched_at,
            "from_cache": from_cache,
            "pinned_names": await _pinned_names(session),
        },
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}/context", response_class=HTMLResponse)
async def get_task_context(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    cutoff = datetime.now(timezone.utc) - timedelta(days=_TTL_DAYS)
    result = await session.execute(
        select(TaskContext)
        .where(
            and_(
                TaskContext.task_id == task_id,
                TaskContext.source == "nexus",
                TaskContext.stale == False,  # noqa: E712
                TaskContext.fetched_at > cutoff,
            )
        )
        .order_by(TaskContext.fetched_at.desc())
        .limit(1)
    )
    cached = result.scalar_one_or_none()

    if cached:
        entities = json.loads(cached.snippet)
        fetched_at = cached.fetched_at
        from_cache = True
    else:
        entities = await _fetch_and_cache(task, session)
        fetched_at = datetime.now(timezone.utc)
        from_cache = False

    return await _render_panel(request, task_id, entities, fetched_at, from_cache, session)


@router.post("/tasks/{task_id}/context/refresh", response_class=HTMLResponse)
async def refresh_task_context(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    entities = await _fetch_and_cache(task, session)
    return await _render_panel(
        request, task_id, entities, datetime.now(timezone.utc), False, session
    )


# ── Entities panel ────────────────────────────────────────────────────────────

async def _get_panel_data(task: Task, session: AsyncSession) -> dict:
    """Fetch attached entities + Nexus suggestions (filtered, query-boosted)."""
    # All attached entities (manual first, then auto)
    result = await session.execute(
        select(TaskEntity)
        .where(TaskEntity.task_id == task.id)
        .order_by(TaskEntity.source.desc(), TaskEntity.entity_name)
    )
    attached = list(result.scalars())
    attached_names = {e.entity_name for e in attached}

    # Boost query with manually-attached entity names for better recall
    manual = [e for e in attached if e.source == "manual"]
    query = _query_text(task)
    if manual:
        query += " " + " ".join(e.entity_name for e in manual[:5])

    # Fetch suggestions, filter already-attached, cap at 10
    client = get_nexus_client()
    data = await client.query_context(query)
    raw = data.get("entities", [])[:15]
    suggestions = [
        {
            "name": e.get("entity_name", ""),
            "type": e.get("entity_type", ""),
            "description": e.get("description", ""),
        }
        for e in raw
        if e.get("entity_name") and e.get("entity_name") not in attached_names
    ][:10]

    return {"attached": attached, "suggestions": suggestions}


async def _render_ep(
    request: Request, task_id: uuid.UUID, session: AsyncSession, task: Task
) -> HTMLResponse:
    data = await _get_panel_data(task, session)
    return get_templates().TemplateResponse(
        request,
        "_partials/entities_panel.html",
        {"task_id": str(task_id), **data},
    )


@router.get("/tasks/{task_id}/entities-panel", response_class=HTMLResponse)
async def get_entities_panel(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return await _render_ep(request, task_id, session, task)


@router.post("/tasks/{task_id}/entities/attach", response_class=HTMLResponse)
async def attach_entities(
    request: Request, task_id: uuid.UUID, data: AttachEntities, session: Session
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    for name in data.entity_names:
        name = name.strip()
        if not name:
            continue
        existing = await session.execute(
            select(TaskEntity).where(
                and_(TaskEntity.task_id == task_id, TaskEntity.entity_name == name)
            )
        )
        if not existing.scalar_one_or_none():
            session.add(
                TaskEntity(
                    task_id=task_id,
                    entity_name=name,
                    source="manual",
                    relevance=1.0,
                )
            )
    await session.commit()
    return await _render_ep(request, task_id, session, task)


@router.post("/tasks/{task_id}/entities/detach", response_class=HTMLResponse)
async def detach_entity(
    request: Request, task_id: uuid.UUID, data: DetachEntity, session: Session
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    await session.execute(
        TaskEntity.__table__.delete().where(
            and_(
                TaskEntity.__table__.c.task_id == task_id,
                TaskEntity.__table__.c.entity_name == data.entity_name,
            )
        )
    )
    await session.commit()
    return await _render_ep(request, task_id, session, task)
