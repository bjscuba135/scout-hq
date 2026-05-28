from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import case, func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import VALID_DOMAINS, VALID_PRIORITIES, VALID_STATUSES
from app.db.models import EntityPin, Task, TaskRun
from app.db.session import get_session
from app.templating import get_templates

router = APIRouter(tags=["tasks"])
templates = get_templates()

Session = Annotated[AsyncSession, Depends(get_session)]


# ── Schemas ───────────────────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    body: str | None = None
    domain: str | None = "scouting"
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
    domain: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    due_date: date | None = None
    owner: str | None = None
    requires_approval: bool | None = None
    parent_id: uuid.UUID | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        """Date inputs send empty string when cleared — treat as None."""
        if v == "" or v is None:
            return None
        return v


class NoteAppend(BaseModel):
    note: str


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


# ── List view ─────────────────────────────────────────────────────────────────

@router.get("/tasks", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def list_tasks(
    request: Request,
    session: Session,
    domain: str | None = None,
    category: str | None = None,
    status: str | None = None,
):
    stmt = select(Task)
    filters = []
    if domain and domain != "all":
        filters.append(Task.domain == domain)
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

    # Domain counts for the filter bar
    counts_result = await session.execute(
        select(Task.domain, func.count(Task.id))
        .where(Task.status != "cancelled")
        .group_by(Task.domain)
    )
    domain_counts = {"all": 0}
    for d, c in counts_result.all():
        domain_counts[d or "scouting"] = c
        domain_counts["all"] += c

    pins_result = await session.execute(
        select(EntityPin).order_by(EntityPin.entity_name).limit(20)
    )
    pins = list(pins_result.scalars())

    ctx = {
        "tasks": tasks,
        "current_domain": domain or "all",
        "current_category": category,
        "current_status": status,
        "domains": sorted(VALID_DOMAINS),
        "domain_counts": domain_counts,
        "statuses": list(VALID_STATUSES),
        "today": date.today(),
        "pins": pins,
    }

    hx_target = request.headers.get("HX-Target", "")
    hx_boosted = request.headers.get("HX-Boosted") == "true"
    if _is_htmx(request) and (hx_target == "task-table-wrap" or not hx_boosted):
        return templates.TemplateResponse(request, "tasks/_table.html", ctx)
    return templates.TemplateResponse(request, "tasks/list.html", ctx)


# ── New task drawer — MUST be before /tasks/{task_id} to avoid UUID capture ──

@router.get("/tasks/new", response_class=HTMLResponse)
async def new_task_drawer(request: Request):
    return templates.TemplateResponse(
        request, "tasks/_drawer.html",
        {"task": None, "domains": sorted(VALID_DOMAINS)}
    )


# ── Detail view ───────────────────────────────────────────────────────────────

@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def get_task(request: Request, task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return templates.TemplateResponse(
        request, "tasks/detail.html",
        {"task": task, "domains": sorted(VALID_DOMAINS), "today": date.today()}
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("/tasks", response_class=HTMLResponse, status_code=201)
async def create_task(request: Request, data: TaskCreate, session: Session):
    _validate_task_fields(data.priority, data.status)
    task = Task(**data.model_dump())
    session.add(task)
    await session.commit()
    await session.refresh(task)

    if _is_htmx(request):
        return templates.TemplateResponse(
            request,
            "tasks/_row.html",
            {"task": task, "today": date.today()},
            status_code=201,
        )
    return templates.TemplateResponse(
        request, "tasks/detail.html", {"task": task, "domains": sorted(VALID_DOMAINS), "today": date.today()},
        status_code=201
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
        if hx_target == "task-main-col":
            return templates.TemplateResponse(
                request,
                "_partials/task_main_col.html",
                {"task": task, "domains": sorted(VALID_DOMAINS), "today": date.today()},
            )
        if hx_target.startswith("task-"):
            return templates.TemplateResponse(
                request, "tasks/_row.html", {"task": task, "today": date.today()}
            )
    return templates.TemplateResponse(
        request, "tasks/detail.html", {"task": task, "domains": sorted(VALID_DOMAINS), "today": date.today()}
    )


# ── Delete (soft) ─────────────────────────────────────────────────────────────

@router.delete("/tasks/{task_id}")
async def delete_task(task_id: uuid.UUID, session: Session):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "cancelled"
    await session.commit()
    return Response(status_code=200)


# ── Append note ───────────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/notes", response_class=HTMLResponse)
async def append_note(
    request: Request, task_id: uuid.UUID, data: NoteAppend, session: Session
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ts = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M")
    note_text = data.note.strip()
    separator = "\n\n" if task.body else ""
    task.body = (task.body or "") + f"{separator}[{ts}] {note_text}"

    await session.commit()
    await session.refresh(task)

    return templates.TemplateResponse(
        request,
        "_partials/task_main_col.html",
        {"task": task, "domains": sorted(VALID_DOMAINS), "today": date.today()},
    )


# ── Dispatch to agent ─────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/dispatch", response_class=HTMLResponse)
async def dispatch_task(
    request: Request, task_id: uuid.UUID, session: Session,
    agent: str = "CC",
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.status = "in_progress"
    run = TaskRun(
        task_id=task.id,
        dispatcher=agent,
        status="queued",
        request_payload={
            "task_id": str(task.id),
            "title": task.title,
            "owner": task.owner,
            "source": "nexus_hq_dispatch_button",
        },
        log=f"Queued for {agent}; no live worker integration has acknowledged this task yet.",
    )
    session.add(run)
    await session.commit()
    short = str(task_id)[:8]
    return HTMLResponse(
        f'<div class="nx-inline-status-msg">'
        f'<strong>Queued {short} for {agent}.</strong> '
        f'Check Approvals/Audit for progress; this button currently queues a TaskRun and does not stream an agent reply.'
        f'</div>'
    )


# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_task_fields(priority: str, status: str):
    _validate_priority(priority)
    _validate_status(status)


def _validate_priority(v: str):
    if v not in VALID_PRIORITIES:
        raise HTTPException(400, f"Invalid priority '{v}'. Must be one of {sorted(VALID_PRIORITIES)}")


def _validate_status(v: str):
    if v not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status '{v}'. Must be one of {sorted(VALID_STATUSES)}")
