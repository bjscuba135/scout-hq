from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.db.session import get_session

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

Session = Depends(get_session)

VALID_CATEGORIES = {
    "admin", "squirrels", "beavers", "cubs", "scouts",
    "hut", "events", "volunteers", "finance",
}


class InboundPayload(BaseModel):
    source: str                          # required, format '<system>:<id>'
    title: str                           # required
    body: str | None = None
    category: str = "admin"
    priority: str = "med"               # high | med | low
    due_date: date | None = None
    suggested_owner: str = "ben"
    requires_approval: bool = False


@router.post("/inbound", status_code=200)
async def inbound_webhook(
    payload: InboundPayload,
    session: AsyncSession = Session,
):
    """
    Create or update a task from an external source.
    Idempotent on (source_system, source_ref) — re-posting the same
    source ID updates the existing task instead of duplicating it.

    Auth: global Basic Auth (same credentials as the UI).
    """
    if payload.category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category '{payload.category}'")

    # Split 'system:ref' → source='system', source_ref='ref'
    if ":" in payload.source:
        source_system, source_ref = payload.source.split(":", 1)
    else:
        source_system, source_ref = payload.source, None

    # Idempotency check
    existing = None
    if source_ref:
        result = await session.execute(
            select(Task).where(
                Task.source == source_system,
                Task.source_ref == source_ref,
            )
        )
        existing = result.scalar_one_or_none()

    if existing:
        existing.title             = payload.title
        existing.body              = payload.body
        existing.category          = payload.category
        existing.priority          = payload.priority
        existing.due_date          = payload.due_date
        existing.owner             = payload.suggested_owner
        existing.requires_approval = payload.requires_approval
        await session.commit()
        return {"action": "updated", "id": str(existing.id)}

    task = Task(
        title             = payload.title,
        body              = payload.body,
        category          = payload.category,
        priority          = payload.priority,
        status            = "open",
        due_date          = payload.due_date,
        owner             = payload.suggested_owner,
        source            = source_system,
        source_ref        = source_ref,
        requires_approval = payload.requires_approval,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return {"action": "created", "id": str(task.id)}
