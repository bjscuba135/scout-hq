from __future__ import annotations

import json
import os
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from app.dispatchers.base import RunStatus
from app.dispatchers.config import DispatcherEntry
from app.dispatchers.schemas import AgentMetadata, TaskMetadata, WorkOrder, WorkOrderCallback

_MISSING = object()


def _get_value(obj: object, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class FileQueueDispatcher:
    """Generic dispatcher that enqueues provider-neutral work orders as JSON files."""

    def __init__(self, entry: DispatcherEntry):
        if not entry.queue_dir:
            raise ValueError("file_queue dispatchers require queue_dir")
        self.entry = entry
        self.type = entry.type
        self.name = entry.name
        self.owner_pattern = entry.owner_pattern
        self.transport = entry.transport or "file_queue"
        self.capabilities = list(entry.capabilities)
        self.queue_dir = Path(entry.queue_dir)

    def can_handle(self, owner: str) -> bool:
        if not owner:
            return False
        for pattern in (self.owner_pattern, self.type, self.name):
            if not pattern:
                continue
            for part in str(pattern).split("|"):
                candidate = part.strip()
                if candidate and (owner == candidate or fnmatch(owner, candidate)):
                    return True
        return False

    async def dispatch(self, task: object, run: object) -> None:
        run_id = _get_value(run, "id", _get_value(run, "run_id", _MISSING))
        if run_id is _MISSING:
            raise ValueError("run must expose id or run_id")

        work_order = WorkOrder(
            run_id=run_id,
            agent=AgentMetadata(
                type=self.entry.type,
                name=self.entry.name,
                transport=self.transport,
                capabilities=self.capabilities,
            ),
            task=TaskMetadata(
                id=_get_value(task, "id"),
                title=_get_value(task, "title", ""),
                body=_get_value(task, "body"),
                domain=_get_value(task, "domain"),
                category=_get_value(task, "category"),
                priority=_get_value(task, "priority"),
                status=_get_value(task, "status"),
                due_date=_get_value(task, "due_date"),
                owner=_get_value(task, "owner"),
            ),
            callback=WorkOrderCallback(
                result_path=str(self.queue_dir / f"{run_id}.result.json"),
            ),
        )

        self.queue_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.queue_dir / f"{run_id}.task.json"
        tmp_path = self.queue_dir / f"{run_id}.task.json.tmp"
        payload = work_order.model_dump(mode="json")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp_path, final_path)

    async def status(self, run: object) -> RunStatus:
        return RunStatus(state="queued")
