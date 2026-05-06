"""Task Nexus context — fetch, cache, and refresh LightRAG snippets per task."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EntityPin, Task, TaskContext, TaskEntity
from app.db.session import get_session
from app.nexus import get_nexus_client
from app.templating import get_templates

router = APIRouter(tags=["context"])
Session = Annotated[AsyncSession, Depends(get_session)]

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
