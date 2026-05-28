from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.nexus.client import NexusClient


def _jwt(exp: datetime | None = None) -> str:
    exp = exp or (datetime.now(timezone.utc) + timedelta(hours=1))
    payload = {"exp": int(exp.timestamp())}
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{payload_b64}.sig"


@pytest.mark.asyncio
async def test_query_context_prefers_api_key_header():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/query/data"
        return httpx.Response(
            200,
            json={"status": "success", "data": {"entities": [{"entity_name": "Apollo"}]}},
        )

    client = NexusClient("http://lightrag", api_key="secret", transport=httpx.MockTransport(handler))

    result = await client.query_context("Apollo NAS")

    assert result == {"entities": [{"entity_name": "Apollo"}]}
    assert len(seen) == 1
    assert seen[0].headers["X-API-Key"] == "secret"
    assert "Authorization" not in seen[0].headers


@pytest.mark.asyncio
async def test_query_context_falls_back_to_guest_jwt_after_api_key_auth_failure():
    seen: list[tuple[str, str | None, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.path,
                request.headers.get("X-API-Key"),
                request.headers.get("Authorization"),
            )
        )
        if request.url.path == "/query/data" and request.headers.get("X-API-Key") == "bad-key":
            return httpx.Response(401, json={"detail": "bad api key"})
        if request.url.path == "/auth-status":
            return httpx.Response(200, json={"access_token": _jwt()})
        if request.url.path == "/query/data" and request.headers.get("Authorization", "").startswith("Bearer "):
            return httpx.Response(200, json={"data": {"chunks": ["fallback worked"]}})
        return httpx.Response(500, json={"detail": "unexpected request"})

    client = NexusClient("http://lightrag", api_key="bad-key", transport=httpx.MockTransport(handler))

    result = await client.query_context("fallback please")

    assert result == {"chunks": ["fallback worked"]}
    assert seen == [
        ("/query/data", "bad-key", None),
        ("/auth-status", None, None),
        ("/query/data", None, f"Bearer {client._token}"),
    ]


@pytest.mark.asyncio
async def test_query_context_accepts_nested_and_plain_data_shapes():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"status": "success", "data": {"relationships": [1]}})
        return httpx.Response(200, json={"entities": ["plain"]})

    client = NexusClient("http://lightrag", api_key="secret", transport=httpx.MockTransport(handler))

    assert await client.query_context("nested") == {"relationships": [1]}
    assert await client.query_context("plain") == {"entities": ["plain"]}


@pytest.mark.asyncio
async def test_search_and_popular_entities_use_api_key_and_degrade_to_empty_lists():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["X-API-Key"] == "secret"
        if request.url.path == "/graph/label/search":
            return httpx.Response(200, json=["Apollo"])
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    client = NexusClient("http://lightrag", api_key="secret", transport=httpx.MockTransport(handler))

    assert await client.search_entities("apo") == ["Apollo"]
    assert await client.popular_entities() == []
    assert paths == ["/graph/label/search", "/graph/label/popular"]


@pytest.mark.asyncio
async def test_health_uses_api_key_when_configured():
    seen_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("X-API-Key"))
        return httpx.Response(200, json={"status": "ok"})

    client = NexusClient("http://lightrag", api_key="secret", transport=httpx.MockTransport(handler))

    assert await client.health() is True
    assert seen_headers == ["secret"]
