from __future__ import annotations

from fnmatch import fnmatch

from app.dispatchers.base import RunStatus


class HumanDispatcher:
    """No-op dispatcher. Tasks owned by 'ben' or 'human' show in UI for manual action."""

    type = "human"
    name: str | None = "Human"
    owner_pattern: str | None = "ben|human"
    transport = "human"
    capabilities = ["manual_review"]
    entry: object | None = None

    def can_handle(self, owner: str) -> bool:
        if not owner:
            return False
        for pattern in (self.owner_pattern, "ben|human"):
            if not pattern:
                continue
            for part in str(pattern).split("|"):
                candidate = part.strip()
                if candidate and (owner == candidate or fnmatch(owner, candidate)):
                    return True
        return False

    async def dispatch(self, task: object, run: object) -> None:
        pass  # human acts via UI

    async def status(self, run: object) -> RunStatus:
        return RunStatus(state="queued")
