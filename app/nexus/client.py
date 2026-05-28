"""LightRAG HTTP client for Nexus HQ."""
from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_AUTH_FALLBACK_STATUSES = {401, 403}


class NexusClient:
    """Async HTTP client for LightRAG (Nexus).

    Prefer explicit LightRAG API-key auth when configured, and fall back to the
    legacy guest JWT from /auth-status for older/local deployments.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._transport = transport
        self._http_client: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_exp: datetime | None = None

    # ── HTTP/auth helpers ─────────────────────────────────────────────────────

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(transport=self._transport)
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _get_token(self) -> str:
        now = datetime.now(timezone.utc)
        # Reuse cached token if it has >60s left
        if (
            self._token
            and self._token_exp
            and (self._token_exp.timestamp() - now.timestamp()) > 60
        ):
            return self._token

        client = self._get_http_client()
        r = await client.get(f"{self.base_url}/auth-status", timeout=5)
        r.raise_for_status()
        data = r.json()
        token = str(data["access_token"])
        self._token = token
        # Decode expiry from JWT payload (no signature verification needed)
        try:
            part = token.split(".")[1]
            part += "=" * (-len(part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(part))
            self._token_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        except Exception:
            self._token_exp = None

        return self._token  # type: ignore[return-value]

    def _api_key_headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _bearer_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        client = self._get_http_client()

        if self.api_key:
            response = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._api_key_headers(),
                timeout=timeout,
            )
            if response.status_code not in _AUTH_FALLBACK_STATUSES:
                response.raise_for_status()
                return response

        token = await self._get_token()
        response = await client.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=self._bearer_headers(token),
            timeout=timeout,
        )
        response.raise_for_status()
        return response

    @staticmethod
    def _context_data(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {}
        data = result.get("data")
        if isinstance(data, dict):
            return data
        return result

    # ── Queries ───────────────────────────────────────────────────────────────

    async def query_context(self, text: str, mode: str = "local") -> dict[str, Any]:
        """Return structured entity/relationship data relevant to *text*.

        Handles both the newer wrapper shape:
            {status, message, data: {entities, relationships, chunks, references}}
        and older/plain dict response shapes.

        Returns empty dict on failure (graceful degradation).
        """
        try:
            r = await self._request(
                "POST",
                "/query/data",
                timeout=15,
                json_body={"query": text, "mode": mode, "only_need_context": True},
            )
            return self._context_data(r.json())
        except Exception as exc:
            logger.warning("LightRAG query_context failed: %s", exc)
            return {}

    async def search_entities(self, q: str, limit: int = 20) -> list[str]:
        """Search entity label names matching *q*."""
        try:
            r = await self._request(
                "GET",
                "/graph/label/search",
                timeout=5,
                params={"q": q, "limit": limit},
            )
            result = r.json()
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("LightRAG search_entities failed: %s", exc)
            return []

    async def popular_entities(self, limit: int = 40) -> list[str]:
        """Return most frequently referenced entity names."""
        try:
            r = await self._request("GET", "/graph/label/popular", timeout=5)
            result = r.json()
            return result[:limit] if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("LightRAG popular_entities failed: %s", exc)
            return []

    async def get_entity_info(self, entity_name: str) -> dict[str, str]:
        """Return {'entity_name', 'entity_type', 'description'} for a named entity.

        Uses GET /graphs?label=<name> which returns the neighbourhood subgraph.
        The response includes all related nodes; the target entity appears as the
        node whose 'id' exactly matches the requested name.

        LightRAG stores multiple descriptions separated by '<SEP>' — we take the
        longest segment as it is typically the most complete.
        """
        empty = {"entity_name": entity_name, "entity_type": "", "description": ""}
        try:
            r = await self._request(
                "GET",
                "/graphs",
                timeout=15,
                params={"label": entity_name},
            )
            data = r.json()
        except Exception as exc:
            logger.warning("LightRAG get_entity_info failed: %s", exc)
            return empty

        name_lower = entity_name.lower()
        nodes = data.get("nodes", []) if isinstance(data, dict) else []

        # Find the node whose id is an exact case-insensitive match
        primary = next(
            (n for n in nodes if n.get("id", "").lower() == name_lower),
            None,
        )
        if not primary:
            return empty

        props = primary.get("properties", {})
        raw_desc = props.get("description", "")

        # Pick the longest <SEP>-separated segment (most complete description)
        if raw_desc and "<SEP>" in raw_desc:
            parts = [p.strip() for p in raw_desc.split("<SEP>") if p.strip()]
            description = max(parts, key=len) if parts else raw_desc
        else:
            description = raw_desc

        return {
            "entity_name": primary.get("id", entity_name),
            "entity_type": props.get("entity_type", ""),
            "description": description,
        }

    async def health(self) -> bool:
        """Return True if LightRAG is reachable."""
        try:
            r = await self._request("GET", "/health", timeout=3)
            return r.status_code == 200
        except Exception:
            return False
