"""Static files with cache busting.

Templates link to `/static/css/app.css?v=<hash of the file>`. When the file changes, the URL
changes too, so browsers can cache static files for a year without ever showing a stale
stylesheet after a deploy.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

STATIC_DIR = Path(__file__).resolve().parent / "static"
ONE_YEAR = 365 * 24 * 60 * 60


@lru_cache
def file_version(path: str) -> str:
    """Short content hash; computed once per file while the app runs (files don't change)."""
    return hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:12]


def static_url(request: Request, path: str) -> str:
    """For templates: {{ static_url(request, 'css/app.css') }}."""
    return f"{request.url_for('static', path=path)}?v={file_version(path)}"


class VersionedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # Only versioned URLs are cached long-term; anything else revalidates as before.
        if response.status_code == 200 and b"v=" in scope.get("query_string", b""):
            response.headers["Cache-Control"] = f"public, max-age={ONE_YEAR}, immutable"
        return response
