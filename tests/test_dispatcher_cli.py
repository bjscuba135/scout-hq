from __future__ import annotations

from pathlib import Path

from app.dispatchers.cli import queue_dirs_from_config
from app.dispatchers.config import DispatcherConfig, DispatcherEntry


def test_queue_dirs_from_config_returns_file_queue_directories_only():
    config = DispatcherConfig(
        dispatchers=[
            DispatcherEntry(type="human", transport="human"),
            DispatcherEntry(type="claude_code", transport="file_queue", queue_dir="/tmp/claude"),
            DispatcherEntry(type="n8n_webhook", transport="webhook", base_url="http://example"),
            DispatcherEntry(type="codex_cli", transport="file_queue", queue_dir="/tmp/codex"),
        ]
    )

    assert queue_dirs_from_config(config) == [Path("/tmp/claude"), Path("/tmp/codex")]
