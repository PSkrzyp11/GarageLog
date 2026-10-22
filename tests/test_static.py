"""Static files: cache busting, long caching of versioned URLs, favicon."""

import re

from fastapi.testclient import TestClient

from app.static_files import file_version

VERSIONED_CSS = re.compile(r'href="http://testserver/static/css/app\.css\?v=([0-9a-f]{12})"')


def test_pages_link_the_stylesheet_with_a_content_hash(client: TestClient) -> None:
    match = VERSIONED_CSS.search(client.get("/login").text)

    assert match
    assert match.group(1) == file_version("css/app.css")


def test_versioned_static_files_are_cached_for_a_year(client: TestClient) -> None:
    url = f"/static/css/app.css?v={file_version('css/app.css')}"

    response = client.get(url)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_unversioned_static_files_are_not_cached_long_term(client: TestClient) -> None:
    response = client.get("/static/css/app.css")

    assert response.status_code == 200
    assert "immutable" not in response.headers.get("cache-control", "")


def test_favicon_redirects_to_the_svg_icon(client: TestClient) -> None:
    response = client.get("/favicon.ico", follow_redirects=False)

    assert response.status_code == 301
    assert "/static/favicon.svg?v=" in response.headers["location"]
    assert (
        client.get(response.headers["location"]).headers["content-type"].startswith("image/svg+xml")
    )


def test_vendored_htmx_is_served(client: TestClient) -> None:
    response = client.get("/static/js/htmx.min.js")

    assert response.status_code == 200
    assert response.text.startswith("var htmx=")
