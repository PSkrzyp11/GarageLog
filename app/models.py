import datetime as dt
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names, so Alembic migrations can refer to (and drop) them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_class: type[StrEnum]) -> Enum:
    """Store an enum as VARCHAR instead of a native PostgreSQL ENUM type.

    Adding a value later is then a simple constraint change in a migration. Allowed values are
    enforced by `enum_check` (Enum's own create_constraint makes Alembic emit it twice).
    """
    return Enum(
        enum_class,
        native_enum=False,
        length=20,
        values_callable=lambda members: [member.value for member in members],
    )


def enum_check(column: str, enum_class: type[StrEnum]) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_class)
    return CheckConstraint(f"{column} IN ({values})", name=f"{column}_values")


class PrimaryFuel(StrEnum):
    PETROL = "petrol"
    DIESEL = "diesel"

    @property
    def label(self) -> str:
        return {"petrol": "Benzyna", "diesel": "Diesel"}[self.value]


class FuelType(StrEnum):
    """What went into the tank. A petrol car with an LPG system takes both."""

    PETROL = "petrol"
    DIESEL = "diesel"
    LPG = "lpg"

    @property
    def label(self) -> str:
        return {"petrol": "Benzyna", "diesel": "Diesel", "lpg": "LPG"}[self.value]


class ServiceCategory(StrEnum):
    MAINTENANCE = "maintenance"
    REPAIR = "repair"
    TIRES = "tires"
    INSPECTION = "inspection"
    INSURANCE = "insurance"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            "maintenance": "Serwis okresowy",
            "repair": "Naprawa",
            "tires": "Opony",
            "inspection": "Badanie techniczne",
            "insurance": "Ubezpieczenie",
            "other": "Inne",
        }[self.value]


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # The app lowercases e-mails; the database guarantees it, so the UNIQUE constraint
        # cannot be bypassed with "Jan@example.com" vs "jan@example.com".
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserSession(Base):
    """A login session. Named UserSession to avoid confusion with SQLAlchemy's Session."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SHA-256 hex digest of the cookie token; the token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)


class Car(Base):
    __tablename__ = "cars"
    __table_args__ = (
        # Also serves as the index for "all cars of a user" (user_id is its first column).
        UniqueConstraint("user_id", "name"),
        # A wide sanity range; the form applies the stricter "not after next year" rule.
        CheckConstraint("production_year BETWEEN 1900 AND 2100", name="production_year_range"),
        enum_check("primary_fuel", PrimaryFuel),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(60))
    production_year: Mapped[int | None] = mapped_column(SmallInteger)
    registration_number: Mapped[str | None] = mapped_column(String(15))
    primary_fuel: Mapped[PrimaryFuel] = mapped_column(enum_column(PrimaryFuel))
    has_lpg: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @property
    def fuel_types(self) -> list[FuelType]:
        """Fuels this car can be refuelled with: its primary fuel, plus LPG if installed."""
        fuels = [FuelType(self.primary_fuel.value)]
        if self.has_lpg:
            fuels.append(FuelType.LPG)
        return fuels


class OdometerReading(Base):
    """A mileage note that is not tied to a refuel or service (e.g. when the car was added).

    The car's current mileage is never stored; it is the highest recorded reading.
    """

    __tablename__ = "odometer_readings"
    __table_args__ = (
        CheckConstraint("odometer_km >= 0", name="odometer_km_non_negative"),
        Index("ix_odometer_readings_car_id_date", "car_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date)
    odometer_km: Mapped[int]
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ServiceEntry(Base):
    """Any cost that is not fuel: service, repair, tyres, inspection, insurance, other."""

    __tablename__ = "service_entries"
    __table_args__ = (
        CheckConstraint("cost_pln >= 0", name="cost_pln_non_negative"),
        CheckConstraint("odometer_km >= 0", name="odometer_km_non_negative"),
        enum_check("category", ServiceCategory),
        Index("ix_service_entries_car_id_date", "car_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date)
    # Optional: old invoices often don't show the mileage.
    odometer_km: Mapped[int | None]
    category: Mapped[ServiceCategory] = mapped_column(enum_column(ServiceCategory))
    title: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    # NUMERIC, not float: money must add up exactly (0.1 + 0.2 == 0.3). Always PLN.
    cost_pln: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FuelEntry(Base):
    """One refuel. The price per litre is not stored: it is total cost ÷ litres."""

    __tablename__ = "fuel_entries"
    __table_args__ = (
        CheckConstraint("liters > 0", name="liters_positive"),
        CheckConstraint("total_cost_pln > 0", name="total_cost_pln_positive"),
        CheckConstraint("odometer_km >= 0", name="odometer_km_non_negative"),
        enum_check("fuel_type", FuelType),
        Index("ix_fuel_entries_car_id_date", "car_id", "date"),
        # Consumption is calculated per fuel type, walking refuels in mileage order.
        Index("ix_fuel_entries_car_id_fuel_type_odometer_km", "car_id", "fuel_type", "odometer_km"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date)
    # Required, unlike for service entries: consumption is impossible without it.
    odometer_km: Mapped[int]
    fuel_type: Mapped[FuelType] = mapped_column(enum_column(FuelType))
    liters: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    total_cost_pln: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    is_full_tank: Mapped[bool]
    # "I forgot to log the refuel before this one": the litres since the last full tank are
    # unknown, so this stretch must not be used to calculate consumption.
    missed_previous: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Reminder(Base):
    """Something to do by a date, by a mileage, or both — whichever comes first."""

    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            "due_date IS NOT NULL OR due_odometer_km IS NOT NULL", name="has_due_condition"
        ),
        CheckConstraint("due_odometer_km >= 0", name="due_odometer_km_non_negative"),
        CheckConstraint("repeat_months BETWEEN 1 AND 120", name="repeat_months_range"),
        CheckConstraint("repeat_km > 0", name="repeat_km_positive"),
        # Active reminders of a car: WHERE car_id = ? AND completed_at IS NULL.
        Index("ix_reminders_car_id_completed_at", "car_id", "completed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    due_date: Mapped[dt.date | None] = mapped_column(Date)
    due_odometer_km: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)
    # Recurring reminder: marking it as done creates the next one, due this many months
    # and/or kilometres after the day and mileage it was done at.
    repeat_months: Mapped[int | None]
    repeat_km: Mapped[int | None]
    # The reminder whose completion created this one; undoing that completion deletes it.
    created_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("reminders.id", ondelete="SET NULL")
    )
    # Set when marked as done; the status (overdue, due soon…) is calculated, never stored.
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
