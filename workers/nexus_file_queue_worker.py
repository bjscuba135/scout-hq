from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable
from uuid import UUID

from app.dispatchers.schemas import WorkerResult, WorkOrder


def _task_files(queue_dir: Path) -> Iterable[Path]:
    return sorted(queue_dir.glob("*.task.json"))


def _matches_worker(work_order: WorkOrder, agent_type: str, capabilities: set[str]) -> bool:
    if work_order.agent.type != agent_type:
        return False
    required = set(work_order.agent.capabilities or [])
    return required.issubset(capabilities) if required else True


def _claim_task(task_path: Path) -> Path | None:
    claimed_path = task_path.with_name(task_path.name + ".claimed")
    try:
        os.replace(task_path, claimed_path)
    except FileNotFoundError:
        return None
    return claimed_path


def _archive_task(claimed_path: Path, run_id: str) -> Path:
    processed = claimed_path.parent / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    archive_path = processed / f"{run_id}.task.json"
    counter = 2
    while archive_path.exists():
        archive_path = processed / f"{run_id}.{counter}.task.json"
        counter += 1
    os.replace(claimed_path, archive_path)
    return archive_path


def _result_path(queue_dir: Path, work_order: WorkOrder) -> Path:
    if work_order.callback.result_path:
        return Path(work_order.callback.result_path)
    return queue_dir / f"{work_order.run_id}.result.json"


def _build_result(work_order: WorkOrder) -> WorkerResult:
    allowed_side_effects = work_order.instructions.allowed_side_effects
    if allowed_side_effects:
        return WorkerResult(
            run_id=UUID(str(work_order.run_id)),
            status="awaiting_approval",
            summary=(
                "Worker inspected task but did not execute requested external side effects: "
                + ", ".join(allowed_side_effects)
            ),
            task_status="waiting",
            notes="The queue worker prototype only acknowledges work orders and reports safely.",
            result={"worker": "nexus_file_queue_worker", "side_effects_blocked": allowed_side_effects},
        )

    return WorkerResult(
        run_id=UUID(str(work_order.run_id)),
        status="succeeded",
        summary=f"Worker acknowledged and completed low-risk task: {work_order.task.title}",
        task_status="done",
        notes="Prototype file-queue worker completed the task without external side effects.",
        result={"worker": "nexus_file_queue_worker"},
    )


def run_once(queue_dir: str | Path, *, agent_type: str, capabilities: set[str] | None = None) -> Path | None:
    queue_path = Path(queue_dir)
    capabilities = capabilities or set()

    for task_path in _task_files(queue_path):
        work_order = WorkOrder.model_validate_json(task_path.read_text(encoding="utf-8"))
        if not _matches_worker(work_order, agent_type, capabilities):
            continue

        claimed_path = _claim_task(task_path)
        if claimed_path is None:
            continue

        try:
            claimed_work_order = WorkOrder.model_validate_json(claimed_path.read_text(encoding="utf-8"))
            result = _build_result(claimed_work_order)
            result_path = _result_path(queue_path, claimed_work_order)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = result_path.with_name(result_path.name + ".tmp")
            tmp_path.write_text(
                json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(tmp_path, result_path)
            _archive_task(claimed_path, str(claimed_work_order.run_id))
            return result_path
        except Exception:
            failed_path = claimed_path.with_suffix(claimed_path.suffix + ".failed")
            os.replace(claimed_path, failed_path)
            raise

    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process one Nexus HQ file-queue task.")
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--agent-type", required=True)
    parser.add_argument("--capability", action="append", default=[])
    args = parser.parse_args(argv)

    result_path = run_once(args.queue_dir, agent_type=args.agent_type, capabilities=set(args.capability))
    if result_path:
        print(result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
