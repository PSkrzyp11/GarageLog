import datetime as dt
from zoneinfo import ZoneInfo

# Entry dates are calendar dates as the user sees them in Poland, not UTC dates.
APP_TIMEZONE = ZoneInfo("Europe/Warsaw")


def today() -> dt.date:
    return dt.datetime.now(APP_TIMEZONE).date()
