from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create(client: AsyncClient, **overrides) -> dict:
    payload = {
        "title": "Test task",
        "category": "admin",
        "priority": "med",
        "status": "open",
        **overrides,
    }
    r = await client.post("/tasks", json=payload)
    assert r.status_code == 201, r.text
    return r


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCreate:
    async def test_create_returns_201(self, client: AsyncClient):
        r = await _create(client, title="Buy milk")
        assert r.status_code == 201

    async def test_create_persists(self, client: AsyncClient, db_session: AsyncSession):
        await _create(client, title="Persist me", category="hut", priority="high")
        from sqlalchemy import select
        result = await db_session.execute(
            select(Task).where(Task.title == "Persist me")
        )
        task = result.scalar_one_or_none()
        assert task is not None
        assert task.category == "hut"
        assert task.priority == "high"

    async def test_invalid_category_rejected(self, client: AsyncClient):
        r = await client.post(
            "/tasks", json={"title": "x", "category": "badcat", "priority": "med"}
        )
        assert r.status_code == 400

    async def test_invalid_priority_rejected(self, client: AsyncClient):
        r = await client.post(
            "/tasks", json={"title": "x", "category": "admin", "priority": "urgent"}
        )
        assert r.status_code == 400


class TestList:
    async def test_list_returns_200(self, client: AsyncClient):
        r = await client.get("/")
        assert r.status_code == 200

    async def test_filter_by_category(self, client: AsyncClient, db_session: AsyncSession):
        await _create(client, title="Squirrel task", category="squirrels")
        await _create(client, title="Admin task", category="admin")

        r = await client.get("/?category=squirrels")
        assert r.status_code == 200
        assert "Squirrel task" in r.text
        assert "Admin task" not in r.text

    async def test_filter_by_status(self, client: AsyncClient):
        await _create(client, title="Waiting task", status="waiting")
        await _create(client, title="Open task", status="open")

        r = await client.get("/?status=waiting")
        assert r.status_code == 200
        assert "Waiting task" in r.text
        assert "Open task" not in r.text

    async def test_htmx_returns_partial(self, client: AsyncClient):
        r = await client.get("/", headers={"HX-Request": "true"})
        assert r.status_code == 200
        # Partial must NOT contain the full <html> wrapper
        assert "<html" not in r.text.lower()


class TestDetail:
    async def _get_task_id(self, db_session: AsyncSession, title: str) -> str:
        from sqlalchemy import select
        result = await db_session.execute(select(Task).where(Task.title == title))
        task = result.scalar_one()
        return str(task.id)

    async def test_detail_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        await _create(client, title="Detail test task")
        tid = await self._get_task_id(db_session, "Detail test task")
        r = await client.get(f"/tasks/{tid}")
        assert r.status_code == 200
        assert "Detail test task" in r.text

    async def test_detail_404(self, client: AsyncClient):
        import uuid
        r = await client.get(f"/tasks/{uuid.uuid4()}")
        assert r.status_code == 404


class TestPatch:
    async def _get_task_id(self, db_session: AsyncSession, title: str) -> str:
        from sqlalchemy import select
        result = await db_session.execute(select(Task).where(Task.title == title))
        task = result.scalar_one()
        return str(task.id)

    async def test_mark_done(self, client: AsyncClient, db_session: AsyncSession):
        await _create(client, title="Mark done task")
        tid = await self._get_task_id(db_session, "Mark done task")

        r = await client.patch(f"/tasks/{tid}", json={"status": "done"})
        assert r.status_code == 200

        db_session.expire_all()
        from sqlalchemy import select
        result = await db_session.execute(select(Task).where(Task.id == tid))
        task = result.scalar_one()
        assert task.status == "done"

    async def test_patch_invalid_status(self, client: AsyncClient, db_session: AsyncSession):
        await _create(client, title="Patch invalid status task")
        tid = await self._get_task_id(db_session, "Patch invalid status task")
        r = await client.patch(f"/tasks/{tid}", json={"status": "exploded"})
        assert r.status_code == 400

    async def test_patch_404(self, client: AsyncClient):
        import uuid
        r = await client.patch(f"/tasks/{uuid.uuid4()}", json={"status": "done"})
        assert r.status_code == 404


class TestDelete:
    async def _get_task_id(self, db_session: AsyncSession, title: str) -> str:
        from sqlalchemy import select
        result = await db_session.execute(select(Task).where(Task.title == title))
        task = result.scalar_one()
        return str(task.id)

    async def test_delete_soft(self, client: AsyncClient, db_session: AsyncSession):
        await _create(client, title="Soft delete task")
        tid = await self._get_task_id(db_session, "Soft delete task")

        r = await client.delete(f"/tasks/{tid}")
        assert r.status_code == 200

        db_session.expire_all()
        from sqlalchemy import select
        result = await db_session.execute(select(Task).where(Task.id == tid))
        task = result.scalar_one()
        assert task.status == "cancelled"
