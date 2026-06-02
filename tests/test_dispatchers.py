from __future__ import annotations

import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.dispatchers.human import HumanDispatcher


def test_load_dispatcher_configs_missing_file_returns_empty(tmp_path):
    from app.dispatchers.config import load_dispatcher_configs

    cfg = load_dispatcher_configs(tmp_path / "missing.yaml")

    assert cfg.dispatchers == []


def test_load_dispatcher_configs_supports_human_file_queue_webhook_and_unknown(tmp_path):
    from app.dispatchers.config import load_dispatcher_configs

    config_path = tmp_path / "dispatchers.yaml"
    config_path.write_text(
        """
        dispatchers:
          - type: human
            name: Human Queue
            owner_pattern: human|ben
            capabilities: [manual_review]
          - type: claude_code
            name: Claude Code
            owner_pattern: claude*
            transport: file_queue
            queue_dir: /opt/AppData/scouthq/queue/claude
            capabilities: [code, shell]
            timeout_seconds: 600
          - type: codex_cli
            name: Codex CLI
            transport: file_queue
            queue_dir: /opt/AppData/scouthq/queue/codex
            capabilities: [code]
          - type: hermes_agent
            name: Hermes Agent
            transport: file_queue
            queue_dir: /opt/AppData/scouthq/queue/hermes
            capabilities: [general, code]
          - type: n8n_webhook
            name: n8n
            transport: webhook
            base_url: http://example.test
            flows:
              email_triage: /webhook/email-triage
            headers:
              X-Scout-HQ: enabled
          - type: future_provider
            name: Future Provider
            transport: custom_transport
        """,
        encoding="utf-8",
    )

    cfg = load_dispatcher_configs(config_path)

    assert [d.type for d in cfg.dispatchers] == [
        "human",
        "claude_code",
        "codex_cli",
        "hermes_agent",
        "n8n_webhook",
        "future_provider",
    ]
    human = cfg.dispatchers[0]
    assert human.name == "Human Queue"
    assert human.transport == "human"
    assert human.owner_pattern == "human|ben"
    claude, codex, hermes = cfg.dispatchers[1:4]
    for entry in (claude, codex, hermes):
        assert entry.transport == "file_queue"
        assert entry.queue_dir.startswith("/opt/AppData/scouthq/queue/")
        assert "code" in entry.capabilities or "general" in entry.capabilities
    webhook = cfg.dispatchers[4]
    assert webhook.base_url == "http://example.test"
    assert webhook.flows == {"email_triage": "/webhook/email-triage"}
    assert webhook.headers == {"X-Scout-HQ": "enabled"}
    assert cfg.dispatchers[5].type == "future_provider"
    assert cfg.dispatchers[5].transport == "custom_transport"


def test_checked_in_dispatchers_yaml_uses_scouthq_queue_and_provider_metadata():
    from app.dispatchers.config import load_dispatcher_configs

    cfg = load_dispatcher_configs("config/dispatchers.yaml")
    by_type = {d.type: d for d in cfg.dispatchers}

    assert by_type["human"].name
    assert by_type["human"].owner_pattern
    assert by_type["human"].transport == "human"
    assert by_type["n8n_webhook"].transport == "webhook"
    assert by_type["n8n_webhook"].capabilities
    assert by_type["claude_code"].transport == "file_queue"
    assert by_type["claude_code"].queue_dir == "/opt/AppData/scouthq/queue/claude"
    assert "/nexushq/" not in by_type["claude_code"].queue_dir
    assert by_type["claude_code"].capabilities
    assert by_type["codex_cli"].name
    assert by_type["gemini_cli"].owner_pattern


def test_dispatcher_registry_includes_human_and_resolves_type_name_owner_and_capability(tmp_path):
    from app.dispatchers.config import DispatcherConfig, DispatcherEntry
    from app.dispatchers.registry import DispatcherRegistry

    cfg = DispatcherConfig(
        dispatchers=[
            DispatcherEntry(type="claude_code", name="Claude Code", owner_pattern="claude*", transport="file_queue", queue_dir=str(tmp_path / "claude"), capabilities=["code", "shell"]),
            DispatcherEntry(type="n8n_webhook", name="n8n", owner_pattern="automation", transport="webhook", base_url="http://example.test", capabilities=["automation"]),
        ]
    )

    registry = DispatcherRegistry(cfg)

    assert isinstance(registry.get("human"), HumanDispatcher)
    assert registry.get("Claude Code").type == "claude_code"
    assert registry.for_owner("claude-review").type == "claude_code"
    claude_dispatcher = registry.get("claude_code")
    assert getattr(claude_dispatcher, "can_handle")("claude-review") is True
    assert registry.for_owner("automation").type == "n8n_webhook"
    assert registry.with_capabilities(["code"]).type == "claude_code"
    assert registry.with_capabilities(["code", "shell"]).type == "claude_code"


def test_dispatcher_registry_unknown_agent_raises_clear_lookup_error():
    from app.dispatchers.config import DispatcherConfig
    from app.dispatchers.registry import DispatcherRegistry

    registry = DispatcherRegistry(DispatcherConfig(dispatchers=[]))

    with pytest.raises(LookupError, match="No dispatcher found"):
        registry.get("missing-agent")
    with pytest.raises(LookupError, match="capabilities"):
        registry.with_capabilities(["telepathy"])


def test_work_order_and_worker_result_json_serialization_and_optional_fields():
    from app.dispatchers.schemas import AgentMetadata, TaskMetadata, WorkerResult, WorkOrder

    run_id = uuid.uuid4()
    work_order = WorkOrder(
        run_id=run_id,
        agent=AgentMetadata(type="claude_code", name="Claude Code", transport="file_queue", capabilities=["code"]),
        task=TaskMetadata(id=uuid.uuid4(), title="Fix bug", body="Details", due_date=date(2026, 6, 2), owner="claude"),
    )

    dumped = work_order.model_dump(mode="json")

    assert dumped["schema_version"] == 1
    assert dumped["run_id"] == str(run_id)
    assert isinstance(dumped["task"]["id"], str)
    assert dumped["task"]["due_date"] == "2026-06-02"
    assert dumped["context"]["entities"] == []
    assert dumped["context"]["snippets"] == []
    assert dumped["instructions"]["mode"] == "assist_and_report"
    assert dumped["instructions"]["approval_required_for_external_side_effects"] is True
    assert dumped["instructions"]["result_contract"] == "write <run_id>.result.json or POST the WorkerResult schema"

    result = WorkerResult(run_id=run_id, status="succeeded", summary="Done", task_status="done")
    result_dumped = result.model_dump(mode="json")
    assert result_dumped["run_id"] == str(run_id)
    assert result_dumped["result"] == {}


def test_worker_result_rejects_unknown_status():
    from app.dispatchers.schemas import WorkerResult

    with pytest.raises(ValueError):
        WorkerResult(run_id=uuid.uuid4(), status="unknown", summary="Nope")


@pytest.mark.asyncio
async def test_file_queue_dispatcher_writes_work_order_atomically(tmp_path):
    from app.dispatchers.config import DispatcherEntry
    from app.dispatchers.file_queue import FileQueueDispatcher

    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = SimpleNamespace(
        id=task_id,
        title="Implement feature",
        body="Feature details",
        domain="engineering",
        category="code",
        priority="high",
        status="open",
        due_date=date(2026, 6, 2),
        owner="claude",
    )
    run = SimpleNamespace(id=run_id)
    entry = DispatcherEntry(
        type="claude_code",
        name="Claude Code",
        owner_pattern="claude*",
        transport="file_queue",
        queue_dir=str(tmp_path / "queue"),
        capabilities=["code", "shell"],
    )
    dispatcher = FileQueueDispatcher(entry)

    await dispatcher.dispatch(task, run)

    final_path = tmp_path / "queue" / f"{run_id}.task.json"
    assert final_path.exists()
    assert list((tmp_path / "queue").glob("*.tmp")) == []
    payload = json.loads(final_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == str(run_id)
    assert payload["agent"] == {
        "type": "claude_code",
        "name": "Claude Code",
        "transport": "file_queue",
        "capabilities": ["code", "shell"],
    }
    assert payload["task"]["id"] == str(task_id)
    assert payload["task"]["title"] == "Implement feature"
    assert payload["task"]["owner"] == "claude"
    assert payload["task"]["due_date"] == "2026-06-02"
    assert payload["callback"]["result_path"] == str(tmp_path / "queue" / f"{run_id}.result.json")
