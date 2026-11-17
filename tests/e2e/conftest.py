"""End-to-end tests: a real browser (Playwright, Chromium) against the app served by uvicorn.

They check what the TestClient tests cannot: HTMX swaps, the chart script, the
Content-Security-Policy as a browser enforces it, pages without JavaScript and on a phone.

    uv sync --group e2e
    uv run playwright install chromium
    uv run pytest tests/e2e

The server uses its own database ("garagelog_e2e_test"), recreated on every run. Data is
committed for real, so every test registers its own account.
"""

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, sync_playwright

from app.config import Settings
from app.main import create_app
from tests.database import fresh_database
from tests.e2e.helpers import NewPage


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    url = fresh_database("e2e")
    settings = Settings(
        _env_file=None, app_env="test", database_url=url.render_as_string(hide_password=False)
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("The app server did not start")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def new_page(browser: Browser, base_url: str) -> Iterator[NewPage]:
    """Opens pages in fresh browser contexts (own cookies). After the test, fails it if any
    page logged a browser error — a script error or anything the CSP blocked."""
    contexts = []
    errors: list[str] = []

    def open_page(**context_options: Any) -> Page:
        options = {"viewport": {"width": 1280, "height": 860}, "locale": "pl-PL"}
        context = browser.new_context(base_url=base_url, **(options | context_options))
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(5_000)
        page.on("console", lambda m: m.type == "error" and errors.append(f"{page.url}: {m.text}"))
        page.on("pageerror", lambda exc: errors.append(f"{page.url}: {exc}"))
        return page

    yield open_page

    for context in contexts:
        context.close()
    assert not errors, "Browser errors:\n" + "\n".join(errors)


@pytest.fixture
def page(new_page: NewPage) -> Page:
    return new_page()
