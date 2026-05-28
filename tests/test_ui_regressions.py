from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task, TaskRun
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
    async def test_htmx_boosted_tasks_navigation_returns_full_page_with_nav(self, client: AsyncClient):
        response = await client.get(
            "/tasks",
            headers={"HX-Request": "true", "HX-Boosted": "true"},
        )

        assert response.status_code == 200, response.text
        assert "nx-topbar" in response.text
        assert "<html" in response.text.lower()

    async def test_task_list_status_control_is_a_real_select(self, client: AsyncClient):
        response = await client.get("/tasks")

        assert response.status_code == 200, response.text
        assert 'name="status"' in response.text
        assert '<select name="status"' in response.text
        assert 'hx-target="#task-table-wrap"' in response.text

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
    async def test_patch_task_detail_main_column_keeps_nexus_layout(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_task(client, title="Detail format", body="Line 1\nLine 2")
        result = await db_session.execute(select(Task).where(Task.title == "Detail format"))
        task = result.scalar_one()

        response = await client.patch(
            f"/tasks/{task.id}",
            json={"body": "Line 1\nLine 2\nLine 3"},
            headers={"HX-Request": "true", "HX-Target": "task-main-col"},
        )

        assert response.status_code == 200, response.text
        assert 'class="nx-detail-main"' in response.text
        assert 'class="nx-meta-row"' in response.text
        assert 'class="nx-action-row"' in response.text
        assert "Line 3" in response.text


class TestApprovalsRendering:
    async def test_dispatch_creates_visible_agent_run_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_task(client, title="Dispatch visibility")
        result = await db_session.execute(select(Task).where(Task.title == "Dispatch visibility"))
        task = result.scalar_one()

        response = await client.post(
            f"/tasks/{task.id}/dispatch",
            json={"agent": "CC"},
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200, response.text
        assert "Queued" in response.text
        assert "does not stream an agent reply" in response.text
        runs = await db_session.execute(select(TaskRun).where(TaskRun.task_id == task.id))
        run = runs.scalar_one()
        assert run.dispatcher == "CC"
        assert run.status == "queued"

    async def test_approvals_awaiting_agent_uses_run_status_not_owner_label(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await _create_task(client, title="Awaiting label", status="in_progress")
        result = await db_session.execute(select(Task).where(Task.title == "Awaiting label"))
        task = result.scalar_one()
        db_session.add(TaskRun(task_id=task.id, dispatcher="CC", status="queued", log="Waiting for worker"))
        await db_session.commit()

        response = await client.get("/approvals")

        assert response.status_code == 200, response.text
        assert "Queued for CC · queued" in response.text
        assert "Waiting for worker" in response.text
        assert "Dispatched to ben" not in response.text

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
    async def test_audit_empty_state_is_visible(self, client: AsyncClient):
        response = await client.get("/audit")

        assert response.status_code == 200, response.text
        assert "No audit entries yet" in response.text

    async def test_htmx_load_more_returns_feed_fragment_not_full_page(self, client: AsyncClient):
        response = await client.get(
            "/audit?before=2099-01-01T00:00:00+00:00",
            headers={"HX-Request": "true"},
        )

        assert response.status_code == 200, response.text
        assert "<html" not in response.text.lower()
        assert "nx-topbar" not in response.text


class TestAskFormAndRoute:
    async def test_ask_form_shows_spinner_and_disables_submit_during_request(self, client: AsyncClient):
        response = await client.get("/ask")

        assert response.status_code == 200
        assert 'hx-indicator="#ask-spinner"' in response.text
        assert 'hx-disabled-elt="button"' in response.text
        assert 'id="ask-spinner"' in response.text

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


class TestSettingsAndEntitiesRendering:
    async def test_settings_agent_selection_returns_config_fragment_not_nested_page(self, client: AsyncClient):
        response = await client.get(
            "/settings/agents?selected=ben",
            headers={"HX-Request": "true", "HX-Target": "nx-settings-config"},
        )

        assert response.status_code == 200, response.text
        assert "<html" not in response.text.lower()
        assert "nx-settings-layout" not in response.text
        assert "LLM routing" in response.text or "Select an agent" in response.text

    async def test_settings_non_agent_sections_render_placeholder_instead_of_duplicate_page(self, client: AsyncClient):
        response = await client.get("/settings/tokens")

        assert response.status_code == 200, response.text
        assert "Token budget controls are planned" in response.text
        assert response.text.count("nx-settings-layout") == 1

    async def test_entity_search_results_use_nexus_entity_row_format(self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
        class FakeNexusClient:
            async def search_entities(self, q: str, limit: int = 15):
                return ["Theresa", "Scouting"]

        monkeypatch.setattr("app.routes.entities.get_nexus_client", lambda: FakeNexusClient())
        response = await client.get("/entities/search?q=sc")

        assert response.status_code == 200, response.text
        assert "nx-entity-result-row" in response.text
        assert "nx-ent-tag" in response.text
        assert "Pin Theresa" in response.text
        assert "search-result-list" not in response.text


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
