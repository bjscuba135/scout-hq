"""LightRAG HTTP client for Scout HQ Nexus integration."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class NexusClient:
    """Async HTTP client for LightRAG (Nexus).

    Auth is disabled on the local instance — we fetch a guest JWT from
    /auth-status and cache it until it expires (typically ~1 hour).
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None
        self._token_exp: datetime | None = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        now = datetime.now(timezone.utc)
        # Reuse cached token if it has >60s left
        if (
            self._token
            and self._token_exp
            and (self._token_exp.timestamp() - now.timestamp()) > 60
        ):
            return self._token

        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{self.base_url}/auth-status")
            r.raise_for_status()
            data = r.json()
            self._token = data["access_token"]
            # Decode expiry from JWT payload (no signature verification needed)
            try:
                part = self._token.split(".")[1]
                part += "=" * (4 - len(part) % 4)
                payload = json.loads(base64.b64decode(part))
                self._token_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            except Exception:
                self._token_exp = None

        return self._token  # type: ignore[return-value]

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # ── Queries ───────────────────────────────────────────────────────────────

    async def query_context(self, text: str, mode: str = "local") -> dict[str, Any]:
        """Return structured entity/relationship data relevant to *text*.

        Response shape:
            {entities: [...], relationships: [...], chunks: [...], references: [...]}
        Returns empty dict on failure (graceful degradation).
        """
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{self.base_url}/query/data",
                    json={"query": text, "mode": mode, "only_need_context": True},
                    headers=self._headers(token),
                )
                r.raise_for_status()
                result = r.json()
                return result.get("data", {})
        except Exception as exc:
            logger.warning("LightRAG query_context failed: %s", exc)
            return {}

    async def search_entities(self, q: str, limit: int = 20) -> list[str]:
        """Search entity label names matching *q*."""
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{self.base_url}/graph/label/search",
                    params={"q": q, "limit": limit},
                    headers=self._headers(token),
                )
                r.raise_for_status()
                result = r.json()
                return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("LightRAG search_entities failed: %s", exc)
            return []

    async def popular_entities(self, limit: int = 40) -> list[str]:
        """Return most frequently referenced entity names."""
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"{self.base_url}/graph/label/popular",
                    headers=self._headers(token),
                )
                r.raise_for_status()
                result = r.json()
                return result[:limit] if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("LightRAG popular_entities failed: %s", exc)
            return []

    async def get_entity_info(self, entity_name: str) -> dict[str, str]:
        """Return {'entity_name', 'entity_type', 'description'} for a named entity.

        Uses POST /query with only_need_context=True which embeds raw Knowledge Graph
        JSON in the text response.  We scan those JSON lines for an exact name match,
        falling back to the first entity found if no exact match exists.

        Example line format in the response text:
            {"entity": "Online Scout Manager", "type": "concept", "description": "..."}
        """
        import json as _json
        import re as _re

        empty = {"entity_name": entity_name, "entity_type": "", "description": ""}
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{self.base_url}/query",
                    json={"query": entity_name, "mode": "local", "only_need_context": True},
                    headers=self._headers(token),
                )
                r.raise_for_status()
                text = r.json().get("response", "")
        except Exception as exc:
            logger.warning("LightRAG get_entity_info failed: %s", exc)
            return empty

        name_lower = entity_name.lower()
        first_hit: dict | None = None

        for line in text.splitlines():
            line = line.strip()
            # Lines look like: {"entity": "...", "type": "...", "description": "..."}
            if not line.startswith("{") or '"entity"' not in line:
                continue
            try:
                obj = _json.loads(line)
            except _json.JSONDecodeError:
                continue

            if first_hit is None:
                first_hit = obj

            if obj.get("entity", "").lower() == name_lower:
                return {
                    "entity_name": obj.get("entity", entity_name),
                    "entity_type": obj.get("type", ""),
                    "description": obj.get("description", ""),
                }

        # No exact match — return first entity as fallback context
        if first_hit:
            return {
                "entity_name": first_hit.get("entity", entity_name),
                "entity_type": first_hit.get("type", ""),
                "description": first_hit.get("description", ""),
            }

        return empty

    async def health(self) -> bool:
        """Return True if LightRAG is reachable."""
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.base_url}/health")
                return r.status_code == 200
        except Exception:
            return False
