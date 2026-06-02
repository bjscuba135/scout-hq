from __future__ import annotations

from fnmatch import fnmatch

from app.dispatchers.base import RunStatus
from app.dispatchers.claude_queue import ClaudeQueueDispatcher
from app.dispatchers.config import DispatcherConfig, DispatcherEntry
from app.dispatchers.file_queue import FileQueueDispatcher
from app.dispatchers.human import HumanDispatcher


class ConfiguredDispatcherAdapter:
    """Lightweight future-provider adapter used until full transports are implemented."""

    def __init__(self, entry: DispatcherEntry):
        self.entry = entry
        self.type = entry.type
        self.name = entry.name
        self.owner_pattern = entry.owner_pattern
        self.transport = entry.transport or "unknown"
        self.capabilities = list(entry.capabilities)

    def can_handle(self, owner: str) -> bool:
        return _matches_owner(self.entry, owner)

    async def dispatch(self, task: object, run: object) -> None:
        raise NotImplementedError(f"Dispatcher transport is not implemented: {self.type} ({self.transport})")

    async def status(self, run: object) -> RunStatus:
        return RunStatus(state="queued")


class DispatcherRegistry:
    def __init__(self, config: DispatcherConfig | None = None):
        self.config = config or DispatcherConfig()
        human = HumanDispatcher()
        for entry in self.config.dispatchers:
            if entry.type == "human":
                human.name = entry.name
                human.owner_pattern = entry.owner_pattern
                human.transport = entry.transport
                human.capabilities = list(entry.capabilities)
                human.entry = entry
                break
        self._dispatchers: list[object] = [human]
        for entry in self.config.dispatchers:
            if entry.type == "human":
                continue
            self._dispatchers.append(self._build_dispatcher(entry))

    @property
    def dispatchers(self) -> list[object]:
        return list(self._dispatchers)

    def get(self, key: str) -> object:
        for dispatcher in self._dispatchers:
            if getattr(dispatcher, "type", None) == key or getattr(dispatcher, "name", None) == key:
                return dispatcher
        raise LookupError(f"No dispatcher found for agent '{key}'")

    def for_owner(self, owner: str) -> object:
        for dispatcher in self._dispatchers:
            can_handle = getattr(dispatcher, "can_handle", None)
            if callable(can_handle) and can_handle(owner):
                return dispatcher
            entry = getattr(dispatcher, "entry", None)
            if isinstance(entry, DispatcherEntry) and _matches_owner(entry, owner):
                return dispatcher
        raise LookupError(f"No dispatcher found for owner '{owner}'")

    def with_capabilities(self, required_capabilities: list[str] | set[str] | tuple[str, ...]) -> object:
        required = set(required_capabilities)
        for dispatcher in self._dispatchers:
            capabilities = set(getattr(dispatcher, "capabilities", []))
            if required.issubset(capabilities):
                return dispatcher
        raise LookupError(f"No dispatcher found with required capabilities: {sorted(required)}")

    def _build_dispatcher(self, entry: DispatcherEntry) -> object:
        if entry.transport == "file_queue":
            if entry.type == "claude_code":
                return ClaudeQueueDispatcher(entry)
            return FileQueueDispatcher(entry)
        return ConfiguredDispatcherAdapter(entry)


def _matches_owner(entry: DispatcherEntry, owner: str) -> bool:
    if not owner:
        return False
    patterns = [entry.owner_pattern, entry.type, entry.name]
    for pattern in patterns:
        if not pattern:
            continue
        for part in str(pattern).split("|"):
            candidate = part.strip()
            if candidate and (owner == candidate or fnmatch(owner, candidate)):
                return True
    return False
