"""A short, readable name of a device from its browser's User-Agent, e.g. "Chrome, Windows".

Only for telling one's own devices apart on the account page, so a rough guess is enough;
there is deliberately no User-Agent library. Order matters: Edge and Opera also say "Chrome",
Chrome also says "Safari", and Android also says "Linux".
"""

BROWSERS = [
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("SamsungBrowser/", "Samsung Internet"),
    ("Firefox/", "Firefox"),
    ("FxiOS/", "Firefox"),
    ("CriOS/", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
]
SYSTEMS = [
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("Macintosh", "Mac"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
]
UNKNOWN = "Nieznane urządzenie"


def describe_device(user_agent: str | None) -> str:
    if not user_agent:
        return UNKNOWN
    browser = next((name for marker, name in BROWSERS if marker in user_agent), None)
    system = next((name for marker, name in SYSTEMS if marker in user_agent), None)
    known = [part for part in (browser, system) if part]
    return ", ".join(known) if known else UNKNOWN
