import datetime as dt

from app.ics import CalendarEvent, calendar

NOW = dt.datetime(2026, 10, 23, 9, 30, tzinfo=dt.UTC)
EVENT = CalendarEvent(
    uid="garagelog-reminder-7",
    day=dt.date(2027, 3, 21),
    summary="Octavia: Wymiana oleju",
    description="Do 21.03.2027 lub do 162 438 km",
)


def unfolded(data: bytes) -> list[str]:
    """The logical lines, with folded continuation lines joined back."""
    return data.decode().replace("\r\n ", "").split("\r\n")


def test_reminder_becomes_an_all_day_event_with_an_alert_the_day_before() -> None:
    lines = unfolded(calendar([EVENT], "GarageLog", NOW))

    assert lines[0] == "BEGIN:VCALENDAR"
    assert "UID:garagelog-reminder-7" in lines
    assert "DTSTAMP:20261023T093000Z" in lines
    assert "DTSTART;VALUE=DATE:20270321" in lines
    assert "DTEND;VALUE=DATE:20270322" in lines
    assert "SUMMARY:Octavia: Wymiana oleju" in lines
    assert "TRIGGER:-PT15H" in lines
    assert lines[-2:] == ["END:VCALENDAR", ""]


def test_lines_end_with_crlf_and_none_is_longer_than_75_bytes() -> None:
    long = CalendarEvent("u", dt.date(2027, 1, 1), "Wymiana łożysk " * 20, "ąęśćżźółń " * 30)

    data = calendar([long], "GarageLog", NOW)

    assert b"\n" not in data.replace(b"\r\n", b"")
    for line in data.split(b"\r\n"):
        assert len(line) <= 75
        line.decode()  # never cut inside a Polish letter
    assert "SUMMARY:" + "Wymiana łożysk " * 20 in unfolded(data)


def test_special_characters_are_escaped() -> None:
    event = CalendarEvent(
        "u", dt.date(2027, 1, 1), "OC; AC, assistance", "Linia 1\nLinia 2 \\ koniec"
    )

    lines = unfolded(calendar([event], "GarageLog", NOW))

    assert "SUMMARY:OC\\; AC\\, assistance" in lines
    assert "DESCRIPTION:Linia 1\\nLinia 2 \\\\ koniec" in lines


def test_empty_calendar_is_still_valid() -> None:
    lines = unfolded(calendar([], "GarageLog", NOW))

    assert "BEGIN:VEVENT" not in lines
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR"
