"""The app in a real browser: the main flow, HTMX, no JavaScript, a phone-sized screen.

Every test also fails on any browser console error (see the `new_page` fixture), so a
script blocked by the Content-Security-Policy or a broken chart is caught on every page.
"""

import datetime as dt
import re

from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    NewPage,
    add_car,
    add_refuel,
    add_reminder,
    add_service,
    mark_page,
    page_was_not_reloaded,
    register,
)


def test_refuels_give_consumption_and_charts(page: Page) -> None:
    register(page)
    car = add_car(page, odometer_km="120000")
    add_refuel(page, car, odometer_km="120 500", liters="40", cost="260,00")
    add_refuel(page, car, odometer_km="121 100", liters="36", cost="230,40")

    page.goto(f"{car}/costs")

    # 36 l over 600 km, between two full tanks.
    expect(page.locator(".consumption")).to_contain_text("6,0 l/100 km")
    expect(page.locator(".chart-box canvas").first).to_be_visible()


def test_history_search_swaps_only_the_list(page: Page) -> None:
    register(page)
    car = add_car(page)
    add_refuel(page, car, odometer_km="120 300", liters="30", cost="200")
    add_service(page, car, title="Wymiana klocków", cost="380")
    page.goto(car)
    mark_page(page)

    page.fill("#q", "klockow")  # without Polish characters on purpose

    expect(page.locator("#timeline li")).to_have_count(1)
    expect(page.locator("#timeline")).to_contain_text("Wymiana klocków")
    expect(page).to_have_url(re.compile(r"[?&]q=klockow"))
    assert page_was_not_reloaded(page)


def test_marking_a_reminder_done_swaps_only_that_item(page: Page) -> None:
    register(page)
    car = add_car(page)
    soon = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    add_reminder(page, car, title="Przegląd", due_date=soon)
    mark_page(page)

    page.get_by_role("button", name="Oznacz jako wykonane").click()

    expect(page.get_by_role("button", name="Przywróć")).to_be_visible()
    assert page_was_not_reloaded(page)


def test_everything_works_without_javascript(new_page: NewPage) -> None:
    page = new_page(java_script_enabled=False)
    register(page)
    car = add_car(page)
    add_refuel(page, car, odometer_km="120 400", liters="35", cost="230")
    add_service(page, car, title="Wymiana klocków", cost="380")

    page.goto(car)
    page.fill("#q", "klocków")
    page.get_by_role("button", name="Pokaż").click()  # a plain GET form, a full page load
    expect(page).to_have_url(re.compile(r"[?&]q=klock%C3%B3w"))
    expect(page.locator("#timeline li")).to_have_count(1)

    page.goto(f"{car}/costs")
    expect(page.locator(".chart-box").first).to_be_hidden()  # the chart needs the script...
    expect(page.locator(".chart-data").first).to_be_attached()  # ...the table does not


def test_pages_fit_a_phone_screen(new_page: NewPage) -> None:
    page = new_page(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True)
    register(page)
    car = add_car(page)
    add_refuel(page, car, odometer_km="120 400", liters="35", cost="230")

    for path in (
        "/",
        car,
        f"{car}/costs",
        f"{car}/years",
        f"{car}/reminders",
        f"{car}/fuel/new",
        "/account",
    ):
        page.goto(path)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, (
            f"{path} scrolls sideways by {overflow}px on a phone; too wide: "
            + ", ".join(page.evaluate(TOO_WIDE))
        )


# The elements that stick out past the right edge of the screen, for the failure message.
TOO_WIDE = """() => {
  const width = document.documentElement.clientWidth;
  return [...document.querySelectorAll("body *")]
    .filter((el) => el.getBoundingClientRect().right > width + 0.5)
    .slice(0, 5)
    .map((el) => `<${el.tagName.toLowerCase()} class="${el.className}">`
                 + ` ${(el.textContent || "").trim().slice(0, 40)}`);
}"""
