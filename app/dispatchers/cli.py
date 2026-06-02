from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Sequence

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.dispatchers.config import DispatcherConfig, load_dispatcher_configs
from app.dispatchers.results import ingest_results_in_directory


def queue_dirs_from_config(config: DispatcherConfig) -> list[Path]:
    """Return configured result queue directories for file-queue transports."""
    return [
        Path(entry.queue_dir)
        for entry in config.dispatchers
        if entry.transport == "file_queue" and entry.queue_dir
    ]


async def ingest_results(queue_dirs: Sequence[str | Path] | None = None) -> int:
    settings = get_settings()
    if queue_dirs is None:
        config = load_dispatcher_configs(settings.dispatchers_config_path)
        directories = queue_dirs_from_config(config)
    else:
        directories = [Path(queue_dir) for queue_dir in queue_dirs]

    processed_count = 0
    async with AsyncSessionLocal() as session:
        for queue_dir in directories:
            processed_count += len(await ingest_results_in_directory(session, queue_dir))
    return processed_count


async def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nexus HQ dispatcher maintenance commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest-results", help="Ingest worker result files")
    ingest_parser.add_argument(
        "--queue-dir",
        action="append",
        dest="queue_dirs",
        help="Queue directory to scan. May be passed multiple times. Defaults to all configured file queues.",
    )

    args = parser.parse_args(argv)
    if args.command == "ingest-results":
        count = await ingest_results(args.queue_dirs)
        print(f"processed {count} result file(s)")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
