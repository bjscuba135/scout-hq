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

    async def health(self) -> bool:
        """Return True if LightRAG is reachable."""
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.base_url}/health")
                return r.status_code == 200
        except Exception:
            return False
