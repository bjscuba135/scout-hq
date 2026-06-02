from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AgentMetadata(BaseModel):
    type: str
    name: str | None = None
    transport: str
    capabilities: list[str] = Field(default_factory=list)


class TaskMetadata(BaseModel):
    id: UUID | str
    title: str
    body: str | None = None
    domain: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    due_date: date | str | None = None
    owner: str | None = None


class WorkOrderContext(BaseModel):
    entities: list[dict[str, Any]] = Field(default_factory=list)
    snippets: list[dict[str, Any]] = Field(default_factory=list)


class WorkOrderInstructions(BaseModel):
    mode: str = "assist_and_report"
    approval_required_for_external_side_effects: bool = True
    allowed_side_effects: list[str] = Field(default_factory=list)
    result_contract: str = "write <run_id>.result.json or POST the WorkerResult schema"


class WorkOrderCallback(BaseModel):
    result_path: str | None = None
    result_url: str | None = None


class WorkOrder(BaseModel):
    schema_version: Literal[1] = 1
    run_id: UUID | str
    agent: AgentMetadata
    task: TaskMetadata
    context: WorkOrderContext = Field(default_factory=WorkOrderContext)
    instructions: WorkOrderInstructions = Field(default_factory=WorkOrderInstructions)
    callback: WorkOrderCallback = Field(default_factory=WorkOrderCallback)


class WorkerResult(BaseModel):
    schema_version: Literal[1] = 1
    run_id: UUID
    status: Literal["succeeded", "failed", "cancelled", "awaiting_approval"]
    summary: str
    task_status: Literal["done", "waiting", "open", "in_progress"] | None = None
    notes: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    cost_tokens: int | None = None
