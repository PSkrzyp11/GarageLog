"""Retake the README screenshots and GIF (docs/screenshots/) from the demo account.

Needs the "e2e" dependency group (Playwright), Chromium and ffmpeg (for the GIF), and an app
whose database holds *only* demo data — seed_demo --reset wipes it. For example:

    DEMO_PASSWORD=... python -m scripts.seed_demo --reset      # on a scratch database!
    uv run uvicorn app.main:create_app --factory --port 8001
    GARAGELOG_URL=http://127.0.0.1:8001 DEMO_PASSWORD=... uv run python -m scripts.take_screenshots

The GIF adds a refuel, so seed the database again before the next run.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
DESKTOP = {"width": 1280, "height": 860}


def login(page: Page, base: str, password: str) -> None:
    page.goto(f"{base}/login")
    page.fill("#email", "demo@example.com")
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(f"{base}/")


def car_path(page: Page, base: str, name: str) -> str:
    page.goto(f"{base}/")
    href = page.get_by_role("link", name=name, exact=True).first.get_attribute("href") or ""
    match = re.search(r"/cars/\d+", href)
    assert match, f"no car {name!r} on the dashboard — is this the demo account?"
    return f"{base}{match.group(0)}"


def wait_for_charts(page: Page) -> None:
    page.wait_for_selector(".chart-box:not([hidden]) canvas")
    page.wait_for_timeout(800)  # Chart.js animation


def screenshots(browser: Browser, base: str, password: str) -> None:
    desktop = browser.new_page(viewport=DESKTOP, color_scheme="light", locale="pl-PL")
    login(desktop, base, password)
    octavia, astra = car_path(desktop, base, "Octavia"), car_path(desktop, base, "Astra")

    desktop.goto(f"{base}/")
    desktop.screenshot(path=OUT / "dashboard.png", full_page=True)

    desktop.goto(octavia)
    desktop.screenshot(path=OUT / "history.png")

    desktop.goto(f"{astra}/costs?period=12m")
    wait_for_charts(desktop)
    desktop.locator(".consumption details").first.evaluate("d => d.open = true")
    desktop.screenshot(path=OUT / "costs.png", full_page=True)
    desktop.locator(".charts").screenshot(path=OUT / "charts.png")

    desktop.goto(f"{octavia}/years")
    wait_for_charts(desktop)
    desktop.screenshot(path=OUT / "years.png", full_page=True)

    desktop.goto(f"{octavia}/reminders")
    desktop.screenshot(path=OUT / "reminders.png", full_page=True)

    # A validation error: a refuel dated in the past with a mileage higher than today's.
    desktop.goto(f"{octavia}/fuel/new")
    desktop.fill("#date", "2025-12-01")
    desktop.fill("#odometer_km", "999 999")
    desktop.fill("#liters", "45,2")
    desktop.fill("#total_cost_pln", "289,90")
    desktop.click("button[type=submit] >> text=Dodaj tankowanie")
    desktop.wait_for_selector(".field-error")
    desktop.screenshot(path=OUT / "validation.png")

    dark = browser.new_page(viewport=DESKTOP, color_scheme="dark", locale="pl-PL")
    login(dark, base, password)
    dark.goto(f"{octavia}/costs")
    wait_for_charts(dark)
    dark.screenshot(path=OUT / "dark.png")

    mobile = browser.new_page(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        color_scheme="light",
        locale="pl-PL",
    )
    login(mobile, base, password)
    mobile.goto(f"{astra}/costs")
    mobile.screenshot(path=OUT / "mobile-costs.png")


def refuel_video(browser: Browser, base: str, password: str, video_dir: Path) -> Path:
    """A refuel added from the dashboard on a phone-sized screen, recorded as WebM."""
    size = {"width": 430, "height": 760}
    context = browser.new_context(
        viewport=size,
        is_mobile=True,
        color_scheme="light",
        locale="pl-PL",
        record_video_dir=video_dir,
        record_video_size=size,
    )
    page = context.new_page()
    login(page, base, password)
    page.wait_for_timeout(1200)
    page.locator(".car-card", has_text="Octavia").get_by_role("link", name="+ Tankowanie").click()
    page.wait_for_selector("#odometer_km")
    page.wait_for_timeout(900)
    hint = page.locator(".field", has=page.locator("#odometer_km")).inner_text()
    last_km = int(re.sub(r"\D", "", hint.split("Ostatni zapisany:")[1]))
    page.type("#odometer_km", str(last_km + 642), delay=90)
    page.type("#liters", "41,7", delay=110)
    page.type("#total_cost_pln", "264,30", delay=110)
    page.check("#is_full_tank")
    page.wait_for_timeout(700)
    page.click("button[type=submit] >> text=Dodaj tankowanie")
    page.wait_for_selector("nav.tabs")
    page.wait_for_timeout(2000)
    page.locator("nav.tabs").get_by_role("link", name="Koszty").click()
    page.wait_for_load_state()
    page.wait_for_timeout(1500)
    page.mouse.wheel(0, 500)
    page.wait_for_timeout(1800)
    assert page.video
    video = Path(page.video.path())
    context.close()
    return video


def to_gif(video: Path, gif: Path, palette: Path) -> None:
    filters = "fps=10,scale=430:-1:flags=lanczos"
    quiet = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(video)]
    subprocess.run([*quiet, "-vf", f"{filters},palettegen=max_colors=96", str(palette)], check=True)
    use_palette = f"{filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4"
    subprocess.run([*quiet, "-i", str(palette), "-lavfi", use_palette, str(gif)], check=True)


def main() -> None:
    base = os.environ.get("GARAGELOG_URL", "http://127.0.0.1:8000").rstrip("/")
    password = os.environ["DEMO_PASSWORD"]
    with sync_playwright() as playwright, tempfile.TemporaryDirectory() as tmp:
        # --lang: Chromium's own widgets (the date field) in Polish, as the page is.
        browser = playwright.chromium.launch(
            args=["--lang=pl"], env={**os.environ, "LANG": "pl_PL.UTF-8", "LANGUAGE": "pl"}
        )
        screenshots(browser, base, password)
        video = refuel_video(browser, base, password, Path(tmp))
        browser.close()
        to_gif(video, OUT / "add-refuel.gif", Path(tmp) / "palette.png")
    print("\n".join(sorted(f"{f.name}: {f.stat().st_size // 1024} KB" for f in OUT.iterdir())))


if __name__ == "__main__":
    main()
