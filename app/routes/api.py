from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["api"])

Session = Depends(get_session)


def _task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "title": task.title,
        "body": task.body,
        "category": task.category,
        "priority": task.priority,
        "status": task.status,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "owner": task.owner,
        "source": task.source,
        "source_ref": task.source_ref,
        "parent_id": str(task.parent_id) if task.parent_id else None,
        "requires_approval": task.requires_approval,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


@router.get("/tasks")
async def api_list_tasks(
    session: AsyncSession = Session,
    status: str | None = None,
    category: str | None = None,
    source: str | None = None,
    source_ref: str | None = None,
    parent_id: uuid.UUID | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Task)
    filters = []
    if status:
        filters.append(Task.status == status)
    if category:
        filters.append(Task.category == category)
    if source:
        filters.append(Task.source == source)
    if source_ref:
        filters.append(Task.source_ref == source_ref)
    if parent_id is not None:
        filters.append(Task.parent_id == parent_id)
    if q:
        filters.append(Task.title.ilike(f"%{q}%") | Task.body.ilike(f"%{q}%"))
    if filters:
        stmt = stmt.where(and_(*filters))
    result = await session.execute(stmt)
    return [_task_to_dict(t) for t in result.scalars().all()]


@router.get("/tasks/{task_id}")
async def api_get_task(
    task_id: uuid.UUID, session: AsyncSession = Session
) -> dict[str, Any]:
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _task_to_dict(task)
