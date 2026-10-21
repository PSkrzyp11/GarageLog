from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.security import csrf_input

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Jinja2Templates enables autoescaping for .html files, which protects against XSS.
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["csrf_input"] = csrf_input


def render(
    request: Request,
    name: str,
    context: Mapping[str, Any] | None = None,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> HTMLResponse:
    # Defaults every template may rely on; the caller's context overrides them.
    full_context = {"user": None, "errors": {}, **(context or {})}
    return templates.TemplateResponse(
        request, name, full_context, status_code=status_code, headers=headers
    )
