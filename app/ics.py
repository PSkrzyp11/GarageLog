"""Reminder due dates as an iCalendar (.ics) file, to import into Google, Apple or Outlook
calendars (RFC 5545, written by hand — the format is small and a library would be overkill).

- Every reminder with a due date becomes an all-day event with an alert the day before.
- Each event has a stable UID, so importing a newer file updates the same events instead of
  adding copies.
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

PRODUCT_ID = "-//GarageLog//Przypomnienia//PL"
# For an all-day event the start is midnight, so -15 h is 9:00 on the day before.
ALERT_BEFORE = "-PT15H"
_MAX_LINE_OCTETS = 75


@dataclass(frozen=True)
class CalendarEvent:
    uid: str
    day: dt.date
    summary: str
    description: str


def calendar(events: Iterable[CalendarEvent], name: str, now: dt.datetime) -> bytes:
    stamp = now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODUCT_ID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for event in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{stamp}",
            # All-day: DTEND is the next day (exclusive), dates without a time or time zone.
            f"DTSTART;VALUE=DATE:{event.day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{event.day + dt.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(event.summary)}",
            f"DESCRIPTION:{_escape(event.description)}",
            "TRANSP:TRANSPARENT",  # a reminder, not a meeting: the day is not "busy"
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(event.summary)}",
            f"TRIGGER:{ALERT_BEFORE}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines).encode()


def _escape(text: str) -> str:
    """Characters with a meaning in iCalendar text values, and line breaks."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def _fold(line: str) -> str:
    """Lines longer than 75 bytes continue on the next line after CRLF + space (RFC 5545 §3.1),
    cut between characters, never inside a multi-byte "ą" or "ż"."""
    parts = []
    current = ""
    limit = _MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode()) > limit:
            parts.append(current)
            current = ""
            limit = _MAX_LINE_OCTETS - 1  # the leading space counts
        current += char
    parts.append(current)
    return "\r\n ".join(parts)
