"""Odometer consistency rule (pure functions, no database).

Rule: for one car the mileage never decreases as dates go forward. Entries may be added in any
order (e.g. old invoices typed in later), so a new value is checked against both sides:

- an EARLIER date with a HIGHER mileage is a conflict,
- a LATER date with a LOWER mileage is a conflict.

Entries on the same day are not compared — the order of events within a day is unknown.
Equal mileage on different days is fine (the car was not driven).
"""

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

from app.formatting import format_date, format_km


@dataclass(frozen=True)
class OdometerPoint:
    date: dt.date
    odometer_km: int
    label: str  # how the entry is named in the error message, e.g. "Odczyt licznika"


@dataclass(frozen=True)
class OdometerConflict:
    point: OdometerPoint
    point_is_later: bool

    @property
    def message(self) -> str:
        where = "Późniejszy" if self.point_is_later else "Wcześniejszy"
        compared = "mniejszy" if self.point_is_later else "większy"
        return (
            f"{where} wpis — {self.point.label} z {format_date(self.point.date)} — ma "
            f"{compared} przebieg ({format_km(self.point.odometer_km)}). "
            "Przebieg nie może maleć z upływem czasu."
        )


def find_conflict(
    points: Iterable[OdometerPoint], date: dt.date, odometer_km: int
) -> OdometerConflict | None:
    """The most telling conflicting entry for a new (date, mileage), or None if it fits."""
    points = list(points)

    earlier_higher = [p for p in points if p.date < date and p.odometer_km > odometer_km]
    if earlier_higher:
        # The highest one shows the smallest mileage the new entry would need.
        return OdometerConflict(max(earlier_higher, key=lambda p: p.odometer_km), False)

    later_lower = [p for p in points if p.date > date and p.odometer_km < odometer_km]
    if later_lower:
        return OdometerConflict(min(later_lower, key=lambda p: p.odometer_km), True)

    return None
