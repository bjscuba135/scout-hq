# Scout HQ

Personal web cockpit for Ben Colley, Group Lead Volunteer at 1st Beetley Scout Group.

Lives at `https://scouthq.local` on the home network, and via Tailscale when away.

## Stack

| Component | Choice |
|---|---|
| Web framework | FastAPI + HTMX 2.x + Jinja2 |
| Database | Postgres 16 + pgvector |
| Reverse proxy | Caddy 2 (internal CA) |
| Deploy | DockHand from `bjscuba135/nexus-constellation` |

## Development

```bash
# Install dependencies (Python 3.12+)
pip install -e ".[dev]"

# Run locally (needs a Postgres instance)
SCOUTHQ_PG_HOST=localhost uvicorn app.main:app --reload --port 3200

# Run migrations
alembic upgrade head

# Run tests (testcontainers spins up Postgres automatically)
pytest
```

## Import legacy tasks

```bash
# After deploying, run these once as docker exec commands:
docker exec scout-hq python -m app.importers.tasks_json /import/tasks.json
docker exec scout-hq python -m app.importers.tasks_md /import/TASKS.md
```

## Phase status

- **Phase 1** — Skeleton service (current)
- Phase 2 — Nexus context integration
- Phase 3 — Dispatcher framework + approval gates
- Phase 4 — Claude Code adapter
- Phase 5 — Inbound ingestion (n8n flows)
- Phase 6 — PWA + Tailscale
- Phase 7+ — Additional adapters, multi-user

See `Plan.md` in the Scout HQ project folder for full spec.
