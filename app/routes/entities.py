"""Entity pins — manage starred LightRAG entities and view their context."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EntityPin, Task, TaskEntity
from app.db.session import get_session
from app.nexus import get_nexus_client
from app.templating import get_templates

router = APIRouter(tags=["entities"])
Session = Annotated[AsyncSession, Depends(get_session)]


# ── Schemas ───────────────────────────────────────────────────────────────────

class PinCreate(BaseModel):
    entity_name: str
    entity_type: str | None = None
    pin_level: str = "favourite"


class UnpinRequest(BaseModel):
    entity_name: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _all_pins(session: AsyncSession) -> list[EntityPin]:
    result = await session.execute(
        select(EntityPin).order_by(EntityPin.pin_level, EntityPin.entity_name)
    )
    return list(result.scalars())


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/entities", response_class=HTMLResponse)
async def entities_page(request: Request, session: Session):
    templates = get_templates()
    pins = await _all_pins(session)
    popular = await get_nexus_client().popular_entities(limit=30)
    pinned_names = {p.entity_name for p in pins}
    return templates.TemplateResponse(
        request,
        "entities/list.html",
        {"pins": pins, "popular": popular, "pinned_names": pinned_names},
    )


@router.get("/entities/pinned", response_class=HTMLResponse)
async def pinned_sidebar(request: Request, session: Session):
    """Sidebar fragment — pinned entities list for the dashboard."""
    templates = get_templates()
    pins = await _all_pins(session)
    return templates.TemplateResponse(
        request, "_partials/pinned_entities_list.html", {"pins": pins}
    )


@router.get("/entities/search", response_class=HTMLResponse)
async def search_entities(request: Request, session: Session, q: str = ""):
    templates = get_templates()
    if not q or len(q) < 2:
        return HTMLResponse("")
    names = await get_nexus_client().search_entities(q, limit=15)
    result = await session.execute(select(EntityPin.entity_name))
    pinned_names = {row[0] for row in result}
    return templates.TemplateResponse(
        request,
        "_partials/entity_search_results.html",
        {"names": names, "pinned_names": pinned_names},
    )


@router.post("/entities/pin", response_class=HTMLResponse)
async def pin_entity(request: Request, data: PinCreate, session: Session):
    templates = get_templates()
    existing = await session.execute(
        select(EntityPin).where(EntityPin.entity_name == data.entity_name)
    )
    if not existing.scalar_one_or_none():
        session.add(
            EntityPin(
                entity_name=data.entity_name,
                entity_type=data.entity_type or None,
                pin_level=data.pin_level,
            )
        )
        await session.commit()
    pins = await _all_pins(session)
    return templates.TemplateResponse(
        request, "_partials/pinned_entities_list.html", {"pins": pins}
    )


@router.post("/entities/unpin", response_class=HTMLResponse)
async def unpin_entity(request: Request, data: UnpinRequest, session: Session):
    templates = get_templates()
    result = await session.execute(
        select(EntityPin).where(EntityPin.entity_name == data.entity_name)
    )
    pin = result.scalar_one_or_none()
    if pin:
        await session.delete(pin)
        await session.commit()
    pins = await _all_pins(session)
    return templates.TemplateResponse(
        request, "_partials/pinned_entities_list.html", {"pins": pins}
    )


@router.get("/entities/{entity_name:path}", response_class=HTMLResponse)
async def entity_detail(request: Request, entity_name: str, session: Session):
    templates = get_templates()

    pin_result = await session.execute(
        select(EntityPin).where(EntityPin.entity_name == entity_name)
    )
    pin = pin_result.scalar_one_or_none()

    # hybrid mode gives better recall for specific named entities than local
    client = get_nexus_client()
    data = await client.query_context(entity_name, mode="hybrid")
    raw_entities = data.get("entities", [])

    name_lower = entity_name.lower()

    # 1. Exact match, 2. substring match (either direction), 3. first result
    def _match_score(e: dict) -> int:
        n = e.get("entity_name", "").lower()
        if n == name_lower:
            return 0
        if name_lower in n or n in name_lower:
            return 1
        return 2

    ranked = sorted(raw_entities, key=_match_score)
    primary = ranked[0] if ranked else None
    description = (primary.get("description") or "") if primary else ""

    # Entity type: pin table → LightRAG result → task_entity table
    entity_type = (pin.entity_type if pin else None) or (
        primary.get("entity_type") if primary else None
    )
    if not entity_type:
        te_type = await session.execute(
            select(TaskEntity.entity_type)
            .where(
                TaskEntity.entity_name == entity_name,
                TaskEntity.entity_type.isnot(None),
            )
            .limit(1)
        )
        row = te_type.first()
        entity_type = row[0] if row else None

    # Related = everything that isn't the primary match (up to 5)
    related = [
        e for e in raw_entities
        if e.get("entity_name", "").lower() != (primary.get("entity_name", "").lower() if primary else "")
    ][:5]

    # Tasks linked to this entity (open/waiting only)
    te_result = await session.execute(
        select(TaskEntity).where(TaskEntity.entity_name == entity_name)
    )
    linked_tasks = []
    for te in te_result.scalars():
        task = await session.get(Task, te.task_id)
        if task and task.status not in ("done", "cancelled"):
            linked_tasks.append(task)

    return templates.TemplateResponse(
        request,
        "entities/detail.html",
        {
            "entity_name": entity_name,
            "entity_type": entity_type,
            "pin": pin,
            "description": description,
            "related": related,
            "linked_tasks": linked_tasks,
        },
    )
