# Nexus HQ

Personal operating cockpit for The Nexus Constellation.

The repository is still named `scout-hq` for compatibility with the existing deployment pipeline, but the app is now branded and packaged as Nexus HQ.

## What it does today

Nexus HQ is a FastAPI + HTMX web app for operating the early Nexus system:

- Task list and task detail workflows
- Domain/category/status filtering
- Entity pins and entity explorer surfaces backed by LightRAG context
- Ask Nexus UI for querying the context graph
- Approval queue, audit log, agent status, and agent settings screens
- Basic Auth protecting browser/API access, with `/healthz` left public for ops checks

## Stack

| Component | Choice |
|---|---|
| Web framework | FastAPI + HTMX 2.x + Jinja2 |
| Database | Postgres 16 + pgvector-ready schema |
| Context/RAG | LightRAG via `app/nexus/client.py` |
| Deploy | DockHand from `bjscuba135/nexus-constellation`, currently under `stacks/ai/scout-hq/` |

## Development

```bash
# Install dependencies (Python 3.12+)
pip install -e ".[dev]"

# Run locally (needs a Postgres instance)
SCOUTHQ_PG_HOST=localhost uvicorn app.main:app --reload --port 3200

# Run migrations
alembic upgrade head

# Run tests
pytest
```

The local test suite uses the test database fixture in `tests/conftest.py`.

## Key configuration

Environment variables are loaded through `app/config.py`.

Common settings:

- `SCOUTHQ_PG_HOST`, `SCOUTHQ_PG_PORT`, `SCOUTHQ_PG_DB`, `SCOUTHQ_PG_USER`, `SCOUTHQ_PG_PASSWORD`
- `SCOUTHQ_USERNAME`, `SCOUTHQ_PASSWORD`
- `NEXUS_BASE_URL` for the LightRAG service
- `LIGHTRAG_API_KEY` for the upcoming API-key auth path
- `DISPATCHERS_CONFIG_PATH` for agent/dispatcher configuration

## Import legacy tasks

```bash
# After deploying, run these once as docker exec commands:
docker exec scout-hq python -m app.importers.tasks_json /import/tasks.json
docker exec scout-hq python -m app.importers.tasks_md /import/TASKS.md
```

## Current roadmap

The next stabilisation work is:

1. Keep tests green as the Nexus HQ rebrand lands.
2. Harden the LightRAG client for API-key auth plus JWT fallback.
3. Pin and validate LightRAG before changing the ingest pipeline.
4. Move from the old custom RAGAnything sidecar to LightRAG's built-in parser pipeline only after representative document tests pass.

See `.hermes/plans/2026-05-26-nexus-hq-lightrag-raganything-plan.md` for the working forward plan.
