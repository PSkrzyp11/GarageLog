"""What a user does in the browser, step by step through the real forms."""

import re
import secrets
from collections.abc import Callable
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect

# The `new_page` fixture: opens a page in a fresh browser context with the given options.
NewPage = Callable[..., Page]

CAR_PAGE = re.compile(r"/cars/\d+$")


def register(page: Page) -> str:
    """Register a new account (every test has its own) and return its e-mail."""
    email = f"e2e-{secrets.token_hex(4)}@example.com"
    password = secrets.token_urlsafe(12)
    page.goto("/register")
    page.fill("#email", email)
    page.fill("#password", password)
    page.fill("#password_confirm", password)
    page.get_by_role("button", name="Załóż konto").click()
    expect(page.get_by_text(email)).to_be_visible()
    return email


def add_car(page: Page, name: str = "Golf", odometer_km: str = "120000") -> str:
    """Add a petrol car without LPG; return the path of its page."""
    page.goto("/cars/new")
    page.fill("#name", name)
    page.select_option("#primary_fuel", "petrol")
    page.fill("#initial_odometer_km", odometer_km)
    page.get_by_role("button", name="Dodaj auto").click()
    expect(page).to_have_url(CAR_PAGE)
    return urlsplit(page.url).path


def add_refuel(page: Page, car: str, odometer_km: str, liters: str, cost: str) -> None:
    """A full-tank refuel dated today (the form's default)."""
    page.goto(f"{car}/fuel/new")
    page.fill("#odometer_km", odometer_km)
    page.fill("#liters", liters)
    page.fill("#total_cost_pln", cost)
    page.check("#is_full_tank")
    page.get_by_role("button", name="Dodaj tankowanie").click()
    expect(page).to_have_url(CAR_PAGE)


def add_service(page: Page, car: str, title: str, cost: str) -> None:
    page.goto(f"{car}/service/new")
    page.fill("#title", title)
    page.fill("#cost_pln", cost)
    page.get_by_role("button", name="Dodaj wpis").click()
    expect(page).to_have_url(CAR_PAGE)


def add_reminder(page: Page, car: str, title: str, due_date: str) -> None:
    page.goto(f"{car}/reminders/new")
    page.fill("#title", title)
    page.fill("#due_date", due_date)
    page.get_by_role("button", name="Dodaj przypomnienie").click()
    expect(page).to_have_url(re.compile(r"/reminders"))


def mark_page(page: Page) -> None:
    """Leave a marker in the page's JavaScript: it survives an HTMX swap, not a page load."""
    page.evaluate("window.e2eMarker = true")


def page_was_not_reloaded(page: Page) -> bool:
    return page.evaluate("window.e2eMarker === true")
