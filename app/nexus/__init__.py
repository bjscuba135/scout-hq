"""Nexus package — LightRAG integration for Scout HQ."""
from functools import lru_cache

from app.nexus.client import NexusClient


@lru_cache(maxsize=1)
def get_nexus_client() -> NexusClient:
    """Return the application-wide NexusClient singleton."""
    from app.config import get_settings
    return NexusClient(base_url=get_settings().nexus_base_url)
