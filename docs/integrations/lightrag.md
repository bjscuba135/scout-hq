# LightRAG integration

Nexus HQ talks to LightRAG through `app/nexus/client.py`.

## Runtime configuration

- `NEXUS_BASE_URL` points to the LightRAG HTTP server.
- `LIGHTRAG_API_KEY` is available in settings and should be used by the next client hardening pass.

The current client still fetches a guest JWT from `/auth-status` and sends it as a bearer token for graph/query endpoints. This matches the existing local deployment assumption, but upstream LightRAG is moving toward API-key auth shapes that should be supported explicitly.

## Endpoints Nexus HQ depends on

| Feature | Method/path | Notes |
|---|---|---|
| Health | `GET /health` | Used by `/healthz`; returns `nexus: ok` only when reachable. |
| Structured task context | `POST /query/data` | Sent JSON: `{query, mode, only_need_context: true}`. Current code expects useful context under `data`. |
| Entity search | `GET /graph/label/search` | Query params: `q`, `limit`; expected response is a list of labels. |
| Popular entities | `GET /graph/label/popular` | Expected response is a list of labels. |
| Entity detail | `GET /graphs?label=<entity>` | Expected response includes `nodes`; target node has `id` matching the entity label and `properties.description` / `properties.entity_type`. |
| Legacy/guest auth | `GET /auth-status` | Current client reads `access_token` and decodes JWT `exp` for caching. |

## Desired next behaviour

The next client update should:

1. Prefer `X-API-Key: $LIGHTRAG_API_KEY` when configured.
2. Fall back to `/auth-status` bearer JWT only when API-key auth is unavailable or fails with an auth-specific response.
3. Keep graceful degradation: UI features should return empty lists/dicts rather than breaking the whole page when LightRAG is unavailable.
4. Use short timeouts for health/entity lookups and moderate timeouts for `/query/data` and `/graphs`.
5. Add mocked `httpx` tests for API-key auth, JWT fallback, nested `/query/data` parsing, and failure behaviour.

## Upgrade caution

Do not delete or re-index LightRAG data as part of client hardening. Parser and storage changes belong in the separate LightRAG upgrade phase, after the live version/image digest and document status have been captured.
