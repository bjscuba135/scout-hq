from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Task, TaskRun


async def _create_task(client: AsyncClient, **overrides) -> None:
    payload = {
        "title": "Approval dispatch task",
        "category": "admin",
        "priority": "med",
        "status": "open",
        "requires_approval": True,
        "owner": "claude_code",
        **overrides,
    }
    response = await client.post("/tasks", json=payload)
    assert response.status_code == 201, response.text


async def _task_by_title(db_session: AsyncSession, title: str) -> Task:
    result = await db_session.execute(select(Task).where(Task.title == title))
    return result.scalar_one()


class TestApprovalDispatch:
    async def test_approve_uses_shared_dispatcher_and_writes_queue_file(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        tmp_path,
        monkeypatch,
    ):
        queue_dir = tmp_path / "queue" / "claude"
        dispatchers_yaml = tmp_path / "dispatchers.yaml"
        dispatchers_yaml.write_text(
            f"""
dispatchers:
  - type: claude_code
    name: Claude Code
    owner_pattern: claude|claude_code|CC
    transport: file_queue
    queue_dir: {queue_dir}
    capabilities: [code, shell]
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("DISPATCHERS_CONFIG_PATH", str(dispatchers_yaml))
        get_settings.cache_clear()

        await _create_task(client, title="Needs approved dispatch")
        task = await _task_by_title(db_session, "Needs approved dispatch")

        response = await client.post(f"/approvals/{task.id}/approve", headers={"HX-Request": "true"})

        assert response.status_code == 200, response.text
        assert "dispatched" in response.text

        db_session.expire_all()
        refreshed = await _task_by_title(db_session, "Needs approved dispatch")
        assert refreshed.requires_approval is False
        assert refreshed.status == "in_progress"

        result = await db_session.execute(select(TaskRun).where(TaskRun.task_id == task.id))
        run = result.scalar_one()
        assert run.dispatcher == "claude_code"
        assert run.status == "queued"
        assert run.request_payload["source"] == "approval_queue"
        assert (queue_dir / f"{run.id}.task.json").exists()

        get_settings.cache_clear()

    async def test_approve_is_idempotent_and_does_not_double_dispatch(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        tmp_path,
        monkeypatch,
    ):
        queue_dir = tmp_path / "queue" / "claude"
        dispatchers_yaml = tmp_path / "dispatchers.yaml"
        dispatchers_yaml.write_text(
            f"""
dispatchers:
  - type: claude_code
    owner_pattern: claude_code
    transport: file_queue
    queue_dir: {queue_dir}
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("DISPATCHERS_CONFIG_PATH", str(dispatchers_yaml))
        get_settings.cache_clear()

        await _create_task(client, title="Approve once only")
        task = await _task_by_title(db_session, "Approve once only")

        first = await client.post(f"/approvals/{task.id}/approve")
        second = await client.post(f"/approvals/{task.id}/approve")

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert "already handled" in second.text

        result = await db_session.execute(select(TaskRun).where(TaskRun.task_id == task.id))
        assert len(result.scalars().all()) == 1
        assert len(list(queue_dir.glob("*.task.json"))) == 1

        get_settings.cache_clear()

    async def test_approve_dispatch_failure_keeps_task_awaiting_approval(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        tmp_path,
        monkeypatch,
    ):
        dispatchers_yaml = tmp_path / "dispatchers.yaml"
        dispatchers_yaml.write_text(
            """
dispatchers:
  - type: n8n_webhook
    owner_pattern: n8n_webhook
    transport: webhook
    base_url: http://example.invalid
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("DISPATCHERS_CONFIG_PATH", str(dispatchers_yaml))
        get_settings.cache_clear()

        await _create_task(client, title="Approval failure restores", owner="n8n_webhook")
        task = await _task_by_title(db_session, "Approval failure restores")

        response = await client.post(f"/approvals/{task.id}/approve")

        assert response.status_code == 501, response.text
        db_session.expire_all()
        refreshed = await _task_by_title(db_session, "Approval failure restores")
        assert refreshed.requires_approval is True
        assert refreshed.status == "open"

        result = await db_session.execute(select(TaskRun).where(TaskRun.task_id == task.id))
        run = result.scalar_one()
        assert run.status == "failed"

        get_settings.cache_clear()
