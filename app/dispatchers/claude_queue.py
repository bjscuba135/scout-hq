from __future__ import annotations

from app.dispatchers.config import DispatcherEntry
from app.dispatchers.file_queue import FileQueueDispatcher


class ClaudeQueueDispatcher(FileQueueDispatcher):
    """Thin compatibility wrapper for Claude Code file-queue dispatching."""

    def __init__(self, entry: DispatcherEntry):
        super().__init__(entry)
