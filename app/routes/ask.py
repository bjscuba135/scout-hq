"""Ask Nexus — natural language query interface to LightRAG."""
from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.nexus import get_nexus_client
from app.templating import get_templates

router = APIRouter(prefix="/ask", tags=["ask"])
templates = get_templates()

SUGGESTED_PROMPTS = [
    "What are the current open tasks for Scouting?",
    "Which volunteers need DBS renewals soon?",
    "What is the status of the LightRAG retrieval validation?",
    "Summarise recent NHS ERP activity.",
    "What services are running on vm-ai?",
]


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@router.get("", response_class=HTMLResponse)
async def ask_page(request: Request):
    return templates.TemplateResponse(
        request, "ask/index.html",
        {"suggested_prompts": SUGGESTED_PROMPTS, "result": None}
    )


@router.post("", response_class=HTMLResponse)
async def ask_query(
    request: Request,
    query: str = Form(...),
    mode: str = Form("hybrid"),
):
    client = get_nexus_client()
    t0 = time.monotonic()
    try:
        data = await client.query_context(query)
        latency_ms = int((time.monotonic() - t0) * 1000)
        response_text = data.get("response", "") if isinstance(data, dict) else ""
        references = data.get("references", []) if isinstance(data, dict) else []
        entities = data.get("entities", []) if isinstance(data, dict) else []
        error = None
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        response_text = ""
        references = []
        entities = []
        error = str(exc)

    ctx = {
        "suggested_prompts": SUGGESTED_PROMPTS,
        "result": {
            "query": query,
            "mode": mode,
            "response": response_text,
            "references": references,
            "entities": entities,
            "latency_ms": latency_ms,
            "error": error,
        },
    }

    if _is_htmx(request):
        return templates.TemplateResponse(request, "ask/_result.html", ctx)
    return templates.TemplateResponse(request, "ask/index.html", ctx)
