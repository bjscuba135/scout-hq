from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class DispatcherEntry(BaseModel):
    """Provider-neutral dispatcher configuration entry."""

    type: str
    name: str | None = None
    owner_pattern: str | None = None
    transport: str = "unknown"
    queue_dir: str | None = None
    base_url: str | None = None
    flows: dict[str, str] | None = None
    binary: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = None
    headers: dict[str, str] | None = None
    secret_refs: dict[str, str] | None = None

    @model_validator(mode="after")
    def default_transport(self) -> "DispatcherEntry":
        if self.transport != "unknown":
            return self
        if self.type == "human":
            self.transport = "human"
        elif self.queue_dir:
            self.transport = "file_queue"
        elif self.base_url or self.flows:
            self.transport = "webhook"
        elif self.binary:
            self.transport = "cli"
        return self


class DispatcherConfig(BaseModel):
    dispatchers: list[DispatcherEntry] = Field(default_factory=list)


def load_dispatcher_configs(path: str | Path) -> DispatcherConfig:
    config_path = Path(path)
    if not config_path.exists():
        return DispatcherConfig()

    raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw is None:
        return DispatcherConfig()
    if not isinstance(raw, dict):
        raise ValueError(f"Dispatcher config must be a mapping: {config_path}")
    return DispatcherConfig.model_validate(raw)
