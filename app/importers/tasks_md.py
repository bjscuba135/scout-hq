"""
One-shot importer for TASKS.md.

Parses the Markdown task list into DB rows.
Idempotent on (source='tasks_md', source_ref=sha256(title)).

Sections:
  ## Active    → status='open'
  ## Waiting On → status='waiting'
  ## Someday   → status='open', priority='low'
  ## Done      → skipped

Line format (Active):
  - [ ] [p:high|med|low] **Title** - body text…
Line format (Waiting On / Someday):
  - [ ] **Title** - body text…

Usage:
    python -m app.importers.tasks_md /path/to/TASKS.md
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.models import Task

# Matches:  - [ ] [p:high] **Title** - body
# or:       - [ ] **Title** - body
_TASK_LINE = re.compile(
    r"^- \[[ x]\] "                                # bullet + checkbox
    r"(?:\[p:(?P<priority>high|med|low)\] )?"       # optional priority tag
    r"\*\*(?P<title>[^*]+)\*\*"                     # **Title**
    r"(?:\s+.*?[-—]\s+(?P<body>.+))?$",             # optional <anything> — body
    re.MULTILINE,
)

_SECTION_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)

_STATUS_MAP = {
    "Active":     ("open",    None),       # (status, priority_override)
    "Waiting On": ("waiting", "med"),
    "Someday":    ("open",    "low"),
}


def _source_ref(title: str) -> str:
    return hashlib.sha256(title.encode()).hexdigest()[:16]


def _parse_md(text: str) -> list[dict]:
    """Return list of task dicts parsed from the markdown."""
    rows: list[dict] = []

    # Split into sections by ## headings
    sections: list[tuple[str, str]] = []
    parts = _SECTION_HEADING.split(text)
    # parts[0] = text before first heading (ignored)
    # parts[1], parts[2], parts[3], parts[4], ... = heading, content alternating
    it = iter(parts[1:])
    for heading, content in zip(it, it):
        sections.append((heading.strip(), content))

    for heading, content in sections:
        if heading not in _STATUS_MAP:
            continue  # skip ## Done and any unknown sections

        status, priority_override = _STATUS_MAP[heading]

        for m in _TASK_LINE.finditer(content):
            title    = m.group("title").strip()
            body     = (m.group("body") or "").strip() or None
            priority = priority_override or m.group("priority") or "med"

            rows.append({
                "title":      title,
                "body":       body,
                "status":     status,
                "priority":   priority,
                "source_ref": _source_ref(title),
            })

    return rows


async def import_tasks_md(path: str | Path, session: AsyncSession) -> int:
    text = Path(path).read_text(encoding="utf-8")
    rows = _parse_md(text)
    imported = 0

    for row in rows:
        result = await session.execute(
            select(Task).where(
                Task.source == "tasks_md",
                Task.source_ref == row["source_ref"],
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.title    = row["title"]
            existing.body     = row["body"]
            existing.status   = row["status"]
            existing.priority = row["priority"]
        else:
            session.add(Task(
                title      = row["title"],
                body       = row["body"],
                category   = "admin",   # default; recategorise via UI
                priority   = row["priority"],
                status     = row["status"],
                owner      = "ben",
                source     = "tasks_md",
                source_ref = row["source_ref"],
            ))
            imported += 1

    await session.commit()
    return imported


async def _main(path: str):
    settings = get_settings()
    engine   = create_async_engine(settings.database_url, echo=False)
    factory  = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        n = await import_tasks_md(path, session)
    await engine.dispose()
    print(f"tasks_md: imported {n} new tasks from {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.importers.tasks_md <path/to/TASKS.md>")
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
