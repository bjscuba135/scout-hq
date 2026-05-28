from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.nexus.client import NexusClient
from app.templating import get_templates


async def _create_task(client: AsyncClient, **overrides) -> httpx.Response:
    payload = {
        "title": "Regression task",
        "category": "admin",
        "priority": "med",
        "status": "open",
        **overrides,
    }
    response = await client.post("/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response


class TestTaskRowRendering:
    async def test_htmx_create_returns_current_seven_column_task_row(self, client: AsyncClient):
        response = await client.post(
            "/tasks",
            json={"title": "HTMX row", "category": "admin", "priority": "high"},
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 201, response.text
        assert response.text.lstrip().startswith('<tr id="task-')
        assert '<td hx-patch="/tasks/' in response.text
        assert response.text.count("<td") == 7
        assert "nx-title-cell" in response.text

    async def test_patch_row_returns_current_seven_column_task_row(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_task(client, title="Patch row")
        result = await db_session.execute(select(Task).where(Task.title == "Patch row"))
        task = result.scalar_one()

        response = await client.patch(
            f"/tasks/{task.id}",
            json={"status": "done"},
            headers={"HX-Request": "true", "HX-Target": f"task-{task.id}"},
        )

        assert response.status_code == 200, response.text
        assert response.text.lstrip().startswith(f'<tr id="task-{task.id}"')
        assert response.text.count("<td") == 7
        assert "nx-title-cell" in response.text


class TestApprovalsRendering:
    async def test_approvals_page_renders_pending_task_with_due_date(self, client: AsyncClient):
        response = await _create_task(
            client,
            title="Needs approval with date",
            due_date=(date.today() - timedelta(days=1)).isoformat(),
            requires_approval=True,
        )
        assert response.status_code == 201

        approvals = await client.get("/approvals")

        assert approvals.status_code == 200, approvals.text
        assert "Needs approval with date" in approvals.text
        assert "overdue" in approvals.text


class TestAuditRendering:
    async def test_htmx_load_more_returns_feed_fragment_not_full_page(self, client: AsyncClient):
        response = await client.get(
            "/audit?before=2099-01-01T00:00:00+00:00",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200, response.text
        assert "<html" not in response.text.lower()
        assert "nx-topbar" not in response.text


class TestAskFormAndRoute:
    async def test_ask_form_opts_out_of_global_json_encoding(self, client: AsyncClient):
        response = await client.get("/ask")

        assert response.status_code == 200
        assert 'hx-post="/ask"' in response.text
        assert 'hx-ext="ignore:json-enc"' in response.text

    async def test_ask_route_passes_selected_mode_to_nexus_client(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        seen: dict[str, str] = {}

        class FakeNexusClient:
            async def query_context(self, query: str, mode: str = "local"):
                seen["query"] = query
                seen["mode"] = mode
                return {"response": "ok", "references": [], "entities": []}

        monkeypatch.setattr("app.routes.ask.get_nexus_client", lambda: FakeNexusClient())

        response = await client.post(
            "/ask",
            data={"query": "What is slow?", "mode": "hybrid"},
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200, response.text
        assert seen == {"query": "What is slow?", "mode": "hybrid"}
        assert "ok" in response.text


class TestHttpSafety:
    async def test_unsafe_cross_origin_request_is_rejected(self, client: AsyncClient):
        response = await client.post(
            "/tasks",
            json={"title": "CSRF", "category": "admin", "priority": "med"},
            headers={"Origin": "https://evil.example"},
        )

        assert response.status_code == 403

    async def test_livez_is_public_and_does_not_check_external_dependencies(self):
        from httpx import ASGITransport
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/livez")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestApiSafety:
    async def test_api_task_limit_is_clamped_to_safe_range(self, client: AsyncClient):
        response = await client.get("/api/tasks?limit=-5")

        assert response.status_code == 200, response.text
        assert response.json() == []


class TestIconRendering:
    def test_unknown_icon_names_fallback_to_object_icon(self):
        template = get_templates().env.from_string(
            '{% import "_macros.html.j2" as nx %}{{ nx.icon("not-real", 13) }}'
        )

        rendered = template.render()

        assert "nx-icon--ent_object" in rendered

    def test_unknown_entity_types_fallback_to_object_icon(self):
        template = get_templates().env.from_string(
            '{% import "_macros.html.j2" as nx %}{{ nx.entity_icon("project", 18) }}'
        )

        rendered = template.render()

        assert 'data-type="object"' in rendered
        assert "nx-icon--ent_object" in rendered

    def test_reference_doc_icon_renders(self):
        template = get_templates().env.from_string(
            '{% import "_macros.html.j2" as nx %}{{ nx.icon("doc", 13) }}'
        )

        rendered = template.render()

        assert "nx-icon--doc" in rendered


@pytest.mark.asyncio
async def test_nexus_client_reuses_underlying_async_client_until_closed():
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": {"response": "ok"}})

    nexus = NexusClient("http://lightrag", api_key="secret", transport=httpx.MockTransport(handler))

    assert await nexus.query_context("first") == {"response": "ok"}
    first_client = nexus._http_client
    assert first_client is not None

    assert await nexus.query_context("second") == {"response": "ok"}
    assert nexus._http_client is first_client

    await nexus.aclose()
    assert nexus._http_client is None
    assert paths == ["/query/data", "/query/data"]
