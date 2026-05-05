from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class RunStatus(BaseModel):
    state: Literal["queued", "running", "awaiting_approval", "succeeded", "failed", "cancelled"]
    log_tail: str | None = None
    result: dict | None = None
    cost_tokens: int | None = None


class Dispatcher(Protocol):
    type: str

    def can_handle(self, owner: str) -> bool: ...
    async def dispatch(self, task: object, run: object) -> None: ...
    async def status(self, run: object) -> RunStatus: ...
