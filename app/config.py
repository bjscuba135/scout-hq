from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    scouthq_pg_user: str = "scouthq"
    scouthq_pg_password: str = "scouthq"
    scouthq_pg_db: str = "scouthq"
    scouthq_pg_host: str = "scouthq-postgres"
    scouthq_pg_port: int = 5432

    # Security
    scouthq_inbound_token: str = "change-me"

    # External
    lightrag_api_key: str = ""
    litellm_api_key: str = ""
    scouthq_base_url: str = "https://scouthq.local"

    # App
    scouthq_restart: str = "unless-stopped"
    dispatchers_config_path: str = "/app/config/dispatchers.yaml"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.scouthq_pg_user}:{self.scouthq_pg_password}"
            f"@{self.scouthq_pg_host}:{self.scouthq_pg_port}/{self.scouthq_pg_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Alias used by Alembic env.py — we run Alembic in async mode so asyncpg is fine."""
        return self.database_url

    def load_dispatchers(self) -> dict:
        path = Path(self.dispatchers_config_path)
        if not path.exists():
            return {"dispatchers": []}
        with open(path) as f:
            return yaml.safe_load(f) or {"dispatchers": []}


@lru_cache
def get_settings() -> Settings:
    return Settings()
