import pytest

from app.devices import UNKNOWN, describe_device

CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)
EDGE_WINDOWS = CHROME_WINDOWS + " Edg/141.0.0.0"
SAFARI_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1"
)
CHROME_ANDROID = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Mobile Safari/537.36"
)
FIREFOX_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 15.6; rv:144.0) Gecko/20100101 Firefox/144.0"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        (CHROME_WINDOWS, "Chrome, Windows"),
        (EDGE_WINDOWS, "Edge, Windows"),  # Edge also says "Chrome" and "Safari"
        (SAFARI_IPHONE, "Safari, iPhone"),  # an iPhone also says "Mac OS X"
        (CHROME_ANDROID, "Chrome, Android"),  # Android also says "Linux"
        (FIREFOX_MAC, "Firefox, Mac"),
        (FIREFOX_LINUX, "Firefox, Linux"),
        ("curl/8.9.1", UNKNOWN),
        ("", UNKNOWN),
        (None, UNKNOWN),
    ],
)
def test_describe_device(user_agent: str | None, expected: str) -> None:
    assert describe_device(user_agent) == expected
