"""JSON API for programmatic access by agents and scripts.

All endpoints use Basic Auth (same credentials as the browser UI).
Create tasks via POST /webhooks/inbound (idempotent, source-keyed).
All other CRUD is here under /api/tasks.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["api"])

Session = Depends(get_session)

VALID_STATUSES   = {"open", "in_progress", "waiting", "done", "cancelled"}
VALID_PRIORITIES = {"high", "med", "low"}
VALID_CATEGORIES = {
    "admin", "squirrels", "beavers", "cubs", "scouts",
    "hut", "events", "volunteers", "finance",
}


# ── Serialiser ────────────────────────────────────────────────────────────────

def _task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id":               str(task.id),
        "title":            task.title,
        "body":             task.body,
        "category":         task.category,
        "priority":         task.priority,
        "status":           task.status,
        "due_date":         task.due_date.isoformat() if task.due_date else None,
        "owner":            task.owner,
        "source":           task.source,
        "source_ref":       task.source_ref,
        "requires_approval": task.requires_approval,
        "created_at":       task.created_at.isoformat(),
        "updated_at":       task.updated_at.isoformat(),
    }


# ── Schemas ───────────────────────────────────────────────────────────────────

class TaskPatchBody(BaseModel):
    """All fields optional — send only what you want to change."""
    title:    str | None = None
    body:     str | None = None
    category: str | None = None
    priority: str | None = None
    status:   str | None = None
    due_date: date | None = None
    owner:    str | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        return None if v == "" else v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v and v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        if v and v not in VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(VALID_PRIORITIES)}")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v):
        if v and v not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        return v


class NoteBody(BaseModel):
    note: str


# ── GET /api/tasks ─────────────────────────────────────────────────────────────

@router.get("/tasks")
async def api_list_tasks(
    session:  AsyncSession = Session,
    status:   str | None = None,
    category: str | None = None,
    priority: str | None = None,
    owner:    str | None = None,
    source:   str | None = None,
    source_ref: str | None = None,
    q:        str | None = None,
    limit:    int = 200,
) -> list[dict[str, Any]]:
    """List / search tasks.

    Query params (all optional, combinable):
      status    open | in_progress | waiting | done | cancelled
      category  admin | squirrels | beavers | cubs | scouts | hut | events | volunteers | finance
      priority  high | med | low
      owner     ben | claude_code | n8n | ...
      source    manual | email-triage | tasks_md | ...
      source_ref  exact source_ref value
      q         free-text search on title + body (case-insensitive)
      limit     max results (default 200)
    """
    stmt = select(Task)
    filters = []
    if status:
        filters.append(Task.status == status)
    if category:
        filters.append(Task.category == category)
    if priority:
        filters.append(Task.priority == priority)
    if owner:
        filters.append(Task.owner == owner)
    if source:
        filters.append(Task.source == source)
    if source_ref:
        filters.append(Task.source_ref == source_ref)
    if q:
        filters.append(
            Task.title.ilike(f"%{q}%") | Task.body.ilike(f"%{q}%")
        )
    if filters:
        stmt = stmt.where(and_(*filters))
    stmt = stmt.order_by(Task.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [_task_to_dict(t) for t in result.scalars().all()]


# ── GET /api/tasks/{id} ────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}")
async def api_get_task(
    task_id: uuid.UUID, session: AsyncSession = Session
) -> dict[str, Any]:
    """Get a single task by UUID."""
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_to_dict(task)


# ── PATCH /api/tasks/{id} ──────────────────────────────────────────────────────

@router.patch("/tasks/{task_id}")
async def api_patch_task(
    task_id: uuid.UUID,
    body:    TaskPatchBody,
    session: AsyncSession = Session,
) -> dict[str, Any]:
    """Update any subset of task fields. Returns the updated task.

    Common agent patterns:
      Mark done:      {"status": "done"}
      Mark waiting:   {"status": "waiting"}
      Reprioritise:   {"priority": "high"}
      Update body:    {"body": "new description"}
      Set due date:   {"due_date": "2026-06-01"}
      Clear due date: {"due_date": null}
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    update = body.model_dump(exclude_unset=True)
    for field, value in update.items():
        setattr(task, field, value)

    await session.commit()
    await session.refresh(task)
    return _task_to_dict(task)


# ── POST /api/tasks/{id}/notes ─────────────────────────────────────────────────

@router.post("/tasks/{task_id}/notes")
async def api_append_note(
    task_id: uuid.UUID,
    body:    NoteBody,
    session: AsyncSession = Session,
) -> dict[str, Any]:
    """Append a timestamped note to a task's body. Returns the updated task.

    The note is appended as:
        [DD Mon YYYY HH:MM UTC] your note text
    """
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    ts = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    separator = "\n\n" if task.body else ""
    task.body = (task.body or "") + f"{separator}[{ts}] {body.note.strip()}"

    await session.commit()
    await session.refresh(task)
    return _task_to_dict(task)
