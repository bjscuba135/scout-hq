from __future__ import annotations

import json
import uuid

from app.dispatchers.schemas import WorkOrder
from workers.nexus_file_queue_worker import run_once


def _write_work_order(queue_dir, *, run_id=None, agent_type="claude_code", capabilities=None):
    run_id = run_id or uuid.uuid4()
    task_path = queue_dir / f"{run_id}.task.json"
    payload = {
        "schema_version": 1,
        "run_id": str(run_id),
        "agent": {
            "type": agent_type,
            "name": "Test Agent",
            "transport": "file_queue",
            "capabilities": capabilities or ["code", "shell"],
        },
        "task": {
            "id": str(uuid.uuid4()),
            "title": "Smoke-test worker task",
            "body": "No side effects required.",
            "status": "in_progress",
            "owner": agent_type,
        },
        "context": {"entities": [], "snippets": []},
        "instructions": {
            "mode": "assist_and_report",
            "approval_required_for_external_side_effects": True,
            "allowed_side_effects": [],
            "result_contract": "write <run_id>.result.json or POST the WorkerResult schema",
        },
        "callback": {"result_path": str(queue_dir / f"{run_id}.result.json")},
    }
    WorkOrder.model_validate(payload)
    task_path.write_text(json.dumps(payload), encoding="utf-8")
    return run_id, task_path


def test_worker_run_once_claims_task_and_writes_provider_neutral_result(tmp_path):
    run_id, task_path = _write_work_order(tmp_path)

    result_path = run_once(tmp_path, agent_type="claude_code", capabilities={"code", "shell"})

    assert result_path == tmp_path / f"{run_id}.result.json"
    assert result_path.exists()
    assert not task_path.exists()
    assert (tmp_path / "processed" / f"{run_id}.task.json").exists()

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert result["run_id"] == str(run_id)
    assert result["status"] == "succeeded"
    assert result["task_status"] == "done"
    assert "Smoke-test worker task" in result["summary"]
    assert result["result"]["worker"] == "nexus_file_queue_worker"


def test_worker_skips_tasks_for_other_agent_types(tmp_path):
    run_id, task_path = _write_work_order(tmp_path, agent_type="codex_cli")

    result_path = run_once(tmp_path, agent_type="claude_code", capabilities={"code", "shell"})

    assert result_path is None
    assert task_path.exists()
    assert not (tmp_path / f"{run_id}.result.json").exists()


def test_worker_skips_task_when_capabilities_do_not_cover_requested_agent_capabilities(tmp_path):
    run_id, task_path = _write_work_order(tmp_path, capabilities=["code", "shell"])

    result_path = run_once(tmp_path, agent_type="claude_code", capabilities={"code"})

    assert result_path is None
    assert task_path.exists()
    assert not (tmp_path / f"{run_id}.result.json").exists()


def test_worker_writes_awaiting_approval_when_side_effects_are_requested(tmp_path):
    run_id, task_path = _write_work_order(tmp_path)
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    payload["instructions"]["allowed_side_effects"] = ["shell"]
    task_path.write_text(json.dumps(payload), encoding="utf-8")

    result_path = run_once(tmp_path, agent_type="claude_code", capabilities={"code", "shell"})

    assert result_path == tmp_path / f"{run_id}.result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "awaiting_approval"
    assert result["task_status"] == "waiting"
    assert "external side effects" in result["summary"]
