"""Both colour themes stay readable: text has a WCAG 2 contrast of at least 4.5:1 (level AA).

The colours are read straight from app/static/css/app.css, so changing one there is checked
here without updating the test.
"""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[1] / "app" / "static" / "css" / "app.css").read_text(
    encoding="utf-8"
)
DARK_MEDIA = "@media (prefers-color-scheme: dark)"

# (text, background) pairs that appear on the pages.
TEXT_ON_BACKGROUND = [
    ("text", "bg"),
    ("text", "surface"),
    ("muted", "bg"),
    ("muted", "surface"),
    ("primary", "bg"),  # links
    ("primary", "surface"),  # links in cards, secondary buttons
    ("on-primary", "primary"),  # buttons
    ("on-primary", "error"),  # "Usuń" buttons
    ("error", "surface"),
    ("error", "error-bg"),  # error messages, "Zaległe" badges
    ("warning-text", "warning-bg"),  # "Wkrótce" badges, archive notice
    ("success", "success-bg"),  # success messages
    ("fuel", "surface"),  # "Wykonane" badges
]
AA_NORMAL_TEXT = 4.5


def colours(block: str) -> dict[str, str]:
    return dict(re.findall(r"--color-([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def themes() -> dict[str, dict[str, str]]:
    root_start = CSS.index(":root {")
    light = colours(CSS[root_start : CSS.index("}", root_start)])
    dark_start = CSS.index(DARK_MEDIA)
    dark = light | colours(CSS[dark_start : CSS.index("}\n}", dark_start)])
    return {"light": light, "dark": dark}


def luminance(hex_colour: str) -> float:
    """Relative luminance as defined by WCAG 2."""
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    red, green, blue = linear
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_contrast_formula_matches_known_values() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_the_dark_theme_redefines_every_colour() -> None:
    light, dark = themes()["light"], colours(CSS[CSS.index(DARK_MEDIA) :])
    assert set(light) <= set(dark)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("text", "background"), TEXT_ON_BACKGROUND)
def test_text_is_readable(theme: str, text: str, background: str) -> None:
    palette = themes()[theme]

    ratio = contrast(palette[text], palette[background])

    assert ratio >= AA_NORMAL_TEXT, f"{theme}: {text} on {background} is only {ratio:.2f}:1"
