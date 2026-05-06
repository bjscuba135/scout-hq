"""Shared Jinja2 templates instance with custom filters."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent / "templates"


@lru_cache(maxsize=1)
def get_templates() -> Jinja2Templates:
    t = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    # URL-encode a string for use in href attributes
    t.env.filters["urlencode"] = lambda s: quote(str(s), safe="")
    # JSON-encode a string for safe embedding in hx-vals attributes
    t.env.filters["jsonstr"] = lambda s: json.dumps(str(s))
    return t
