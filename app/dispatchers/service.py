from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Task, TaskRun
from app.dispatchers.config import load_dispatcher_configs
from app.dispatchers.registry import DispatcherRegistry


_AGENT_ALIASES = {
    "cc": "claude_code",
    "claude": "claude_code",
    "claude code": "claude_code",
}


def _normalise_agent(agent: str | None) -> str | None:
    if not agent:
        return None
    cleaned = agent.strip()
    return _AGENT_ALIASES.get(cleaned.lower(), cleaned)


def _queue_file_for(dispatcher: object, run_id: uuid.UUID) -> str | None:
    queue_dir = getattr(dispatcher, "queue_dir", None)
    if not queue_dir:
        return None
    return str(Path(queue_dir) / f"{run_id}.task.json")


async def queue_task_dispatch(
    session: AsyncSession,
    task: Task,
    agent: str | None = None,
    source: str = "nexus_hq_dispatch",
    clear_approval: bool = False,
) -> TaskRun:
    """Create a run ledger entry and enqueue a task through the selected dispatcher.

    Nexus HQ remains the state/approval authority. Dispatchers only translate the
    provider-neutral work order onto a transport such as a file queue or webhook.
    """
    settings = get_settings()
    config = load_dispatcher_configs(settings.dispatchers_config_path)
    registry = DispatcherRegistry(config)

    selected_agent = _normalise_agent(agent)
    if selected_agent:
        dispatcher = registry.get(selected_agent)
    else:
        dispatcher = registry.for_owner(task.owner)

    previous_status = task.status
    previous_requires_approval = task.requires_approval
    task.status = "in_progress"
    if clear_approval:
        task.requires_approval = False
    run_id = uuid.uuid4()
    queue_file = _queue_file_for(dispatcher, run_id)
    request_payload: dict[str, Any] = {
        "schema_version": 1,
        "task_id": str(task.id),
        "title": task.title,
        "owner": task.owner,
        "source": source,
        "requested_agent": agent,
        "dispatcher_type": getattr(dispatcher, "type", selected_agent or "unknown"),
        "transport": getattr(dispatcher, "transport", "unknown"),
    }
    if queue_file:
        request_payload["queue_file"] = queue_file

    run = TaskRun(
        id=run_id,
        task_id=task.id,
        dispatcher=getattr(dispatcher, "type", selected_agent or "unknown"),
        status="queued",
        request_payload=request_payload,
        log="Dispatch queued; awaiting worker acknowledgement.",
    )
    session.add(run)
    await session.commit()

    dispatch = getattr(dispatcher, "dispatch", None)
    if not callable(dispatch):
        run.status = "failed"
        run.log = f"Dispatcher {run.dispatcher} does not implement dispatch."
        await session.commit()
        raise NotImplementedError(run.log)
    dispatch_call = cast(Callable[[object, object], Awaitable[None]], dispatch)

    try:
        await dispatch_call(task, run)
    except Exception as exc:
        run.status = "failed"
        run.log = f"Dispatch failed for {run.dispatcher}: {exc}"
        task.status = previous_status
        task.requires_approval = previous_requires_approval
        await session.commit()
        raise

    if queue_file:
        run.log = f"Queued for {run.dispatcher}; wrote work order to {queue_file}."
    else:
        run.log = f"Queued for {run.dispatcher}; dispatch adapter accepted the work order."
    await session.commit()

    return run
