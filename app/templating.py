"""Shared Jinja2 templates instance with custom filters and globals."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# SVG path data for nx_icons — referenced by the {{ icon(name) }} macro.
# Paths are the inner content of a 16×16 viewBox SVG.
_NX_ICONS: dict[str, str] = {
    "list":    '<path d="M5 5h10M5 8h10M5 11h7"/>',
    "node":    '<circle cx="4" cy="4" r="1.5"/><circle cx="12" cy="4" r="1.5"/><circle cx="8" cy="12" r="1.5"/><path d="M4 4l4 8M12 4l-4 8M4 4l8 0"/>',
    "bot":     '<rect x="4" y="6" width="8" height="7" rx="1"/><path d="M8 3v3M6 9h.5M9.5 9h.5"/>',
    "search":  '<circle cx="7" cy="7" r="4"/><path d="M10 10l3.5 3.5"/>',
    "filter":  '<path d="M3 4h10l-4 5v4l-2 1V9z"/>',
    "plus":    '<path d="M8 3v10M3 8h10"/>',
    "chev":    '<path d="M6 4l4 4-4 4"/>',
    "chevd":   '<path d="M4 6l4 4 4-4"/>',
    "bell":    '<path d="M5 11V8a3 3 0 0 1 6 0v3l1 1H4z"/><path d="M7 13a1.5 1.5 0 0 0 2 0"/>',
    "bolt":    '<path d="M9 2L4 9h3l-1 5 5-7H8z"/>',
    "cmd":     '<path d="M5 6a2 2 0 0 1-2-2 1 1 0 1 1 2 0v8a1 1 0 1 1-2 0 2 2 0 0 1 2-2zm6 0a2 2 0 0 0 2-2 1 1 0 1 0-2 0v8a1 1 0 1 0 2 0 2 2 0 0 0-2-2zM5 6h6v4H5z"/>',
    "refresh": '<path d="M3 8a5 5 0 0 1 8.5-3.5L13 6M13 3v3h-3M13 8a5 5 0 0 1-8.5 3.5L3 10M3 13v-3h3"/>',
    "check":   '<path d="M3 8l3 3 7-7"/>',
    "x":       '<path d="M4 4l8 8M12 4l-8 8"/>',
    "doc":     '<path d="M5 2h5l3 3v9H5z"/><path d="M10 2v3h3"/><path d="M7 8h4M7 11h3"/>',
    # Entity type icons
    "ent_person":   '<circle cx="8" cy="5.5" r="2.2"/><path d="M3 13c0-2.4 2.2-4 5-4s5 1.6 5 4"/>',
    "ent_org":      '<rect x="4" y="7" width="8" height="6" rx="1"/><path d="M6 7V5a2 2 0 0 1 4 0v2"/><path d="M8 10v2"/>',
    "ent_system":   '<rect x="3" y="4" width="10" height="7" rx="1"/><path d="M5 14h6M8 11v3"/>',
    "ent_place":    '<path d="M8 2a4 4 0 0 1 4 4c0 3-4 8-4 8S4 9 4 6a4 4 0 0 1 4-4z"/><circle cx="8" cy="6" r="1.5"/>',
    "ent_doc":      '<path d="M5 2h5l3 3v9H5z"/><path d="M10 2v3h3"/><path d="M7 8h4M7 11h3"/>',
    "ent_object":   '<rect x="4" y="4" width="8" height="8" rx="1"/>',
}


@lru_cache(maxsize=1)
def get_templates() -> Jinja2Templates:
    t = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    t.env.filters["urlencode"] = lambda s: quote(str(s), safe="")
    t.env.filters["jsonstr"] = lambda s: json.dumps(str(s))
    # Make nx_icons available to all templates (used by _macros.html.j2)
    t.env.globals["nx_icons"] = _NX_ICONS
    return t
