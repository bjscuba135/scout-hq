"""Audit log — immutable feed of task runs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TaskRun
from app.db.session import get_session
from app.templating import get_templates

router = APIRouter(prefix="/audit", tags=["audit"])
templates = get_templates()

Session = Annotated[AsyncSession, Depends(get_session)]


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _group_by_day(runs: list[TaskRun]) -> list[dict]:
    groups: dict[str, list] = {}
    for run in runs:
        day = run.started_at.astimezone(timezone.utc).strftime("%A %d %B %Y")
        groups.setdefault(day, []).append(run)
    return [{"day": day, "runs": items} for day, items in groups.items()]


@router.get("", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    session: Session,
    before: str | None = None,
    limit: int = 50,
):
    stmt = select(TaskRun).order_by(TaskRun.started_at.desc())
    if before:
        try:
            cutoff = datetime.fromisoformat(before)
            stmt = stmt.where(TaskRun.started_at < cutoff)
        except ValueError:
            pass
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    runs = result.scalars().all()

    ctx = {
        "groups": _group_by_day(runs),
        "runs": runs,
        "next_cursor": runs[-1].started_at.isoformat() if runs else None,
    }
    if before and _is_htmx(request):
        return templates.TemplateResponse(request, "audit/_feed.html", ctx)
    return templates.TemplateResponse(request, "audit/list.html", ctx)
