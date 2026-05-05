from __future__ import annotations

from app.dispatchers.base import RunStatus


class HumanDispatcher:
    """No-op dispatcher. Tasks owned by 'ben' or 'human' show in UI for manual action."""

    type = "human"

    def can_handle(self, owner: str) -> bool:
        return owner in ("ben", "human")

    async def dispatch(self, task: object, run: object) -> None:
        pass  # human acts via UI

    async def status(self, run: object) -> RunStatus:
        return RunStatus(state="queued")
