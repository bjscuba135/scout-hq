"""
One-shot importer for legacy tasks.json.

Reads the tasks array from the JSON file and upserts each task into the DB.
Idempotent on (source='legacy_artefact', source_ref=task.id).

Usage:
    python -m app.importers.tasks_json /path/to/tasks.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Task

_PRIORITY_MAP = {"high": "high", "med": "med", "low": "low"}
_STATUS_MAP   = {"open": "open", "done": "done", "in_progress": "in_progress",
                  "waiting": "waiting", "cancelled": "cancelled"}


async def import_tasks_json(path: str | Path, session: AsyncSession) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = data.get("tasks", [])
    imported = 0

    for t in tasks:
        source_ref = t["id"]

        # Idempotent: check whether this task is already in the DB
        result = await session.execute(
            select(Task).where(
                Task.source == "legacy_artefact",
                Task.source_ref == source_ref,
            )
        )
        existing = result.scalar_one_or_none()

        priority      = _PRIORITY_MAP.get(t.get("priority", "med"), "med")
        status        = _STATUS_MAP.get(t.get("status", "open"), "open")
        due_date_str  = t.get("dueDate")
        due_date      = date.fromisoformat(due_date_str) if due_date_str else None

        if existing:
            existing.title    = t["title"]
            existing.body     = t.get("note")
            existing.category = t.get("category", "admin")
            existing.priority = priority
            existing.status   = status
            existing.due_date = due_date
        else:
            session.add(Task(
                title      = t["title"],
                body       = t.get("note"),
                category   = t.get("category", "admin"),
                priority   = priority,
                status     = status,
                due_date   = due_date,
                owner      = "ben",
                source     = "legacy_artefact",
                source_ref = source_ref,
            ))
            imported += 1

    await session.commit()
    return imported


async def _main(path: str):
    settings = get_settings()
    engine   = create_async_engine(settings.database_url, echo=False)
    factory  = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        n = await import_tasks_json(path, session)
    await engine.dispose()
    print(f"tasks_json: imported {n} new tasks from {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.importers.tasks_json <path/to/tasks.json>")
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
