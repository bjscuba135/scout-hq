from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import TaskRun
from app.dispatchers.schemas import WorkerResult


def _log_text(result: WorkerResult) -> str:
    parts = [result.summary]
    if result.notes:
        parts.append(result.notes)
    return "\n\n".join(parts)


def _append_task_note(existing_body: str | None, result: WorkerResult) -> str:
    note = _log_text(result)
    if not note:
        return existing_body or ""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    dispatch_note = f"[Nexus worker result · {timestamp}]\n{note}"
    if existing_body:
        return f"{existing_body}\n\n{dispatch_note}"
    return dispatch_note


def _processed_path(result_path: Path) -> Path:
    archive_path = result_path.parent / "processed" / result_path.name
    if not archive_path.exists():
        return archive_path

    base_name = result_path.name.removesuffix(".result.json")
    counter = 2
    while True:
        candidate = result_path.parent / "processed" / f"{base_name}.{counter}.result.json"
        if not candidate.exists():
            return candidate
        counter += 1


def _run_id_from_filename(result_path: Path) -> str:
    if not result_path.name.endswith(".result.json"):
        raise ValueError(f"Result file must be named <run_id>.result.json: {result_path}")
    return result_path.name.removesuffix(".result.json")


def _archive_result_file(path: Path) -> Path:
    archive_path = _processed_path(path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    payload = path.read_bytes()

    while True:
        try:
            with archive_path.open("xb") as archive_file:
                archive_file.write(payload)
            path.unlink()
            return archive_path
        except FileExistsError:
            archive_path = _processed_path(path)


async def ingest_result_file(session: AsyncSession, result_path: str | Path) -> Path:
    """Ingest a provider-neutral worker result file and archive it after DB commit."""
    path = Path(result_path)
    result = WorkerResult.model_validate_json(path.read_text(encoding="utf-8"))
    file_run_id = _run_id_from_filename(path)
    if file_run_id != str(result.run_id):
        raise ValueError(
            f"Result filename run_id '{file_run_id}' does not match result payload run_id '{result.run_id}'"
        )

    run_result = await session.execute(
        select(TaskRun)
        .options(selectinload(TaskRun.task))
        .where(TaskRun.id == result.run_id)
        .with_for_update()
    )
    run = run_result.scalar_one_or_none()
    if run is None:
        raise LookupError(f"No TaskRun found for worker result run_id '{result.run_id}'")

    payload = result.model_dump(mode="json")
    already_ingested = run.result_payload == payload
    if not already_ingested:
        task = run.task
        task.body = _append_task_note(task.body, result)
        if result.task_status:
            task.status = result.task_status

    run.status = result.status
    run.finished_at = datetime.now(timezone.utc)
    run.result_payload = payload
    run.log = _log_text(result)
    run.cost_tokens = result.cost_tokens

    await session.commit()

    return _archive_result_file(path)


async def ingest_results_in_directory(session: AsyncSession, queue_dir: str | Path) -> list[Path]:
    """Ingest all result files directly in a queue directory, ignoring tasks and archives."""
    directory = Path(queue_dir)
    if not directory.exists():
        return []

    processed: list[Path] = []
    for result_path in sorted(directory.glob("*.result.json")):
        processed.append(await ingest_result_file(session, result_path))
    return processed
