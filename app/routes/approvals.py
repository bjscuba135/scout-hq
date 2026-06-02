"""Approval queue — tasks requiring human sign-off before dispatch."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.db.session import get_session
from app.dispatchers.service import queue_task_dispatch
from app.templating import get_templates

router = APIRouter(prefix="/approvals", tags=["approvals"])
templates = get_templates()

Session = Annotated[AsyncSession, Depends(get_session)]


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@router.get("", response_class=HTMLResponse)
async def approvals_page(request: Request, session: Session):
    # Needs decision: requires_approval=True, status=open
    pending_result = await session.execute(
        select(Task).where(
            Task.requires_approval == True,
            Task.status == "open",
        ).order_by(Task.due_date.asc().nullslast(), Task.created_at.asc())
    )
    pending = pending_result.scalars().all()

    # Awaiting agent: in_progress (dispatched, not yet done)
    awaiting_result = await session.execute(
        select(Task)
        .options(selectinload(Task.runs))
        .where(Task.status == "in_progress")
        .order_by(Task.updated_at.desc())
    )
    awaiting = awaiting_result.scalars().all()

    # Recently approved: done in last 24h
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_result = await session.execute(
        select(Task).where(
            Task.status == "done",
            Task.updated_at >= cutoff,
        ).order_by(Task.updated_at.desc()).limit(20)
    )
    recent = recent_result.scalars().all()

    ctx = {
        "pending": pending,
        "awaiting": awaiting,
        "recent": recent,
        "pending_count": len(pending),
        "today": date.today(),
    }
    return templates.TemplateResponse(request, "approvals/list.html", ctx)


@router.post("/{task_id}/approve", response_class=HTMLResponse)
async def approve_task(request: Request, task_id: uuid.UUID, session: Session):
    task_result = await session.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if not task.requires_approval or task.status != "open":
        return HTMLResponse(
            f'<div id="toast" hx-swap-oob="true">'
            f'<div class="nx-toast"><span class="nx-toast-dot"></span>'
            f'<span>Approval for {str(task_id)[:8]}… already handled</span></div></div>'
        )
    try:
        await queue_task_dispatch(
            session,
            task,
            agent=task.owner,
            source="approval_queue",
            clear_approval=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # Return OOB toast + redirect signal
    return HTMLResponse(
        f'<div id="toast" hx-swap-oob="true">'
        f'<div class="nx-toast"><span class="nx-toast-dot"></span>'
        f'<span>Approved {str(task_id)[:8]}… — dispatched</span></div></div>'
    )


@router.post("/{task_id}/defer", response_class=HTMLResponse)
async def defer_task(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    ts = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M")
    note = f"\n\n[{ts}] Approval deferred."
    task.body = (task.body or "") + note
    await session.commit()
    return HTMLResponse(
        f'<div id="toast" hx-swap-oob="true">'
        f'<div class="nx-toast"><span class="nx-toast-dot"></span>'
        f'<span>Deferred — added note to task</span></div></div>'
    )
