from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel
from sqlalchemy import case, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.db.session import get_session

router = APIRouter(tags=["tasks"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

Session = Annotated[AsyncSession, Depends(get_session)]

VALID_CATEGORIES = {
    "admin", "squirrels", "beavers", "cubs", "scouts",
    "hut", "events", "volunteers", "finance",
}
VALID_PRIORITIES = {"high", "med", "low"}
VALID_STATUSES = {"open", "in_progress", "waiting", "done", "cancelled"}


# ── Schemas ───────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    body: str | None = None
    category: str = "admin"
    priority: str = "med"
    status: str = "open"
    due_date: date | None = None
    owner: str = "ben"
    source: str = "manual"
    source_ref: str | None = None
    requires_approval: bool = False


class TaskPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    due_date: date | None = None
    owner: str | None = None
    requires_approval: bool | None = None


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


# ── List view ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def list_tasks(
    request: Request,
    session: Session,
    category: str | None = None,
    status: str | None = None,
):
    stmt = select(Task)
    filters = []
    if category:
        filters.append(Task.category == category)
    if status:
        filters.append(Task.status == status)
    if filters:
        stmt = stmt.where(and_(*filters))

    stmt = stmt.order_by(
        case({"high": 0, "med": 1, "low": 2}, value=Task.priority, else_=3),
        Task.due_date.asc().nullslast(),
        Task.created_at.asc(),
    )
    result = await session.execute(stmt)
    tasks = result.scalars().all()

    ctx = {
        "tasks": tasks,
        "current_category": category,
        "current_status": status,
        "categories": sorted(VALID_CATEGORIES),
        "statuses": list(VALID_STATUSES),
        "today": date.today(),
    }

    if _is_htmx(request):
        return templates.TemplateResponse(request, "_partials/task_list_body.html", ctx)
    return templates.TemplateResponse(request, "tasks/list.html", ctx)


# ── Detail view ───────────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def get_task(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return templates.TemplateResponse(request, "tasks/detail.html", {"task": task})


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/tasks", response_class=HTMLResponse, status_code=201)
async def create_task(request: Request, data: TaskCreate, session: Session):
    _validate_task_fields(data.category, data.priority, data.status)
    task = Task(**data.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)

    if _is_htmx(request):
        return templates.TemplateResponse(request, "_partials/task_row.html", {"task": task})
    return templates.TemplateResponse(
        request, "tasks/detail.html", {"task": task}, status_code=201
    )


# ── Update (PATCH) ────────────────────────────────────────────────────────────

@router.patch("/tasks/{task_id}", response_class=HTMLResponse)
async def patch_task(
    request: Request, task_id: uuid.UUID, data: TaskPatch, session: Session
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update = data.model_dump(exclude_unset=True)
    if "category" in update:
        _validate_category(update["category"])
    if "priority" in update:
        _validate_priority(update["priority"])
    if "status" in update:
        _validate_status(update["status"])

    for field, value in update.items():
        setattr(task, field, value)

    await session.commit()
    await session.refresh(task)

    if _is_htmx(request):
        hx_target = request.headers.get("HX-Target", "")
        if hx_target.startswith("task-"):
            # Called from the list view row toggle — return just the row partial
            return templates.TemplateResponse(request, "_partials/task_row.html", {"task": task})
        # Called from the detail page — tell HTMX to navigate to the detail page
        return Response(
            status_code=200,
            headers={"HX-Location": f"/tasks/{task.id}"},
        )
    return templates.TemplateResponse(request, "tasks/detail.html", {"task": task})


# ── Delete (soft) ─────────────────────────────────────────────────────────────

@router.delete("/tasks/{task_id}")
async def delete_task(task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "cancelled"
    await session.commit()
    return Response(status_code=200)


# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_task_fields(category: str, priority: str, status: str):
    _validate_category(category)
    _validate_priority(priority)
    _validate_status(status)


def _validate_category(v: str):
    if v not in VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category '{v}'. Must be one of {sorted(VALID_CATEGORIES)}")


def _validate_priority(v: str):
    if v not in VALID_PRIORITIES:
        raise HTTPException(400, f"Invalid priority '{v}'. Must be one of {sorted(VALID_PRIORITIES)}")


def _validate_status(v: str):
    if v not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status '{v}'. Must be one of {sorted(VALID_STATUSES)}")
