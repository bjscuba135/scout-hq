from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, TaskRun
from app.dispatchers.results import ingest_result_file, ingest_results_in_directory


async def _create_run(db_session: AsyncSession) -> tuple[Task, TaskRun]:
    task = Task(
        title="Worker result task",
        body="Original body",
        domain="scouting",
        category="admin",
        priority="med",
        status="in_progress",
        owner="claude_code",
    )
    db_session.add(task)
    await db_session.flush()
    run = TaskRun(
        id=uuid.uuid4(),
        task_id=task.id,
        dispatcher="claude_code",
        status="queued",
        request_payload={"schema_version": 1},
        log="Queued",
    )
    db_session.add(run)
    await db_session.commit()
    return task, run


class TestDispatcherResultIngestion:
    async def test_ingest_result_file_updates_run_task_and_archives_after_commit(
        self, db_session: AsyncSession, tmp_path
    ):
        task, run = await _create_run(db_session)
        task_id = task.id
        run_id = run.id
        result_file = tmp_path / f"{run.id}.result.json"
        result_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": str(run.id),
                    "status": "succeeded",
                    "summary": "Worker completed the task",
                    "task_status": "done",
                    "notes": "Added useful notes",
                    "result": {"artifact": "abc"},
                    "cost_tokens": 123,
                }
            ),
            encoding="utf-8",
        )

        processed_path = await ingest_result_file(db_session, result_file)

        assert processed_path == tmp_path / "processed" / f"{run.id}.result.json"
        assert processed_path.exists()
        assert not result_file.exists()

        db_session.expire_all()
        run_result = await db_session.execute(select(TaskRun).where(TaskRun.id == run_id))
        refreshed_run = run_result.scalar_one()
        assert refreshed_run.status == "succeeded"
        assert refreshed_run.finished_at is not None
        assert refreshed_run.result_payload["summary"] == "Worker completed the task"
        assert refreshed_run.result_payload["result"]["artifact"] == "abc"
        assert refreshed_run.log == "Worker completed the task\n\nAdded useful notes"
        assert refreshed_run.cost_tokens == 123

        task_result = await db_session.execute(select(Task).where(Task.id == task_id))
        refreshed_task = task_result.scalar_one()
        assert refreshed_task.status == "done"
        assert "Original body" in refreshed_task.body
        assert "Worker completed the task" in refreshed_task.body
        assert "Added useful notes" in refreshed_task.body

    async def test_ingest_result_file_fails_without_archiving_when_run_unknown(
        self, db_session: AsyncSession, tmp_path
    ):
        unknown_run_id = uuid.uuid4()
        result_file = tmp_path / f"{unknown_run_id}.result.json"
        result_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": str(unknown_run_id),
                    "status": "failed",
                    "summary": "No run exists",
                }
            ),
            encoding="utf-8",
        )

        try:
            await ingest_result_file(db_session, result_file)
        except LookupError as exc:
            assert str(unknown_run_id) in str(exc)
        else:
            raise AssertionError("expected LookupError")

        assert result_file.exists()
        assert not (tmp_path / "processed" / f"{unknown_run_id}.result.json").exists()

    async def test_ingest_result_file_rejects_filename_run_id_mismatch_without_archiving(
        self, db_session: AsyncSession, tmp_path
    ):
        _task, run = await _create_run(db_session)
        run_id = run.id
        wrong_file_id = uuid.uuid4()
        result_file = tmp_path / f"{wrong_file_id}.result.json"
        result_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": str(run_id),
                    "status": "succeeded",
                    "summary": "Should not ingest",
                }
            ),
            encoding="utf-8",
        )

        try:
            await ingest_result_file(db_session, result_file)
        except ValueError as exc:
            assert "does not match result payload" in str(exc)
        else:
            raise AssertionError("expected ValueError")

        assert result_file.exists()
        db_session.expire_all()
        run_result = await db_session.execute(select(TaskRun).where(TaskRun.id == run_id))
        assert run_result.scalar_one().status == "queued"

    async def test_ingest_duplicate_result_is_idempotent_and_archives_without_overwrite(
        self, db_session: AsyncSession, tmp_path
    ):
        task, run = await _create_run(db_session)
        task_id = task.id
        run_id = run.id
        payload = {
            "schema_version": 1,
            "run_id": str(run_id),
            "status": "succeeded",
            "summary": "Duplicate-safe summary",
            "task_status": "done",
        }
        first_file = tmp_path / f"{run_id}.result.json"
        first_file.write_text(json.dumps(payload), encoding="utf-8")

        first_archive = await ingest_result_file(db_session, first_file)
        first_archive.write_text("original archive", encoding="utf-8")

        duplicate_file = tmp_path / f"{run_id}.result.json"
        duplicate_file.write_text(json.dumps(payload), encoding="utf-8")

        duplicate_archive = await ingest_result_file(db_session, duplicate_file)

        assert duplicate_archive != first_archive
        assert duplicate_archive.exists()
        assert first_archive.read_text(encoding="utf-8") == "original archive"

        db_session.expire_all()
        task_result = await db_session.execute(select(Task).where(Task.id == task_id))
        refreshed_task = task_result.scalar_one()
        assert refreshed_task.body.count("Duplicate-safe summary") == 1

    async def test_ingest_results_in_directory_processes_only_result_files(
        self, db_session: AsyncSession, tmp_path
    ):
        _task, run = await _create_run(db_session)
        (tmp_path / f"{run.id}.task.json").write_text("{}", encoding="utf-8")
        (tmp_path / f"{run.id}.result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": str(run.id),
                    "status": "cancelled",
                    "summary": "Cancelled by worker",
                    "task_status": "waiting",
                }
            ),
            encoding="utf-8",
        )

        processed = await ingest_results_in_directory(db_session, tmp_path)

        assert processed == [tmp_path / "processed" / f"{run.id}.result.json"]
        run_result = await db_session.execute(select(TaskRun).where(TaskRun.id == run.id))
        assert run_result.scalar_one().status == "cancelled"
