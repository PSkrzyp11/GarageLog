"""receipts for service entries too

Revision ID: e328ceddb777
Revises: 67bc46b28df2
Create Date: 2026-10-23 19:53:57.438535

Written by hand: autogenerate would drop "fuel_receipts" and create "receipts", losing the
stored files. The table is renamed instead (with its constraints, so their names keep matching
the naming convention in app/models.py), and gets a second, optional parent.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e328ceddb777"
down_revision: str | Sequence[str] | None = "67bc46b28df2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMED_CONSTRAINTS = [
    ("pk_fuel_receipts", "pk_receipts"),
    ("uq_fuel_receipts_fuel_entry_id", "uq_receipts_fuel_entry_id"),
    ("fk_fuel_receipts_fuel_entry_id_fuel_entries", "fk_receipts_fuel_entry_id_fuel_entries"),
    ("ck_fuel_receipts_content_type_values", "ck_receipts_content_type_values"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table("fuel_receipts", "receipts")
    op.execute("ALTER SEQUENCE fuel_receipts_id_seq RENAME TO receipts_id_seq")
    for old, new in RENAMED_CONSTRAINTS:
        # Renaming a primary key or unique constraint renames its index too.
        op.execute(f"ALTER TABLE receipts RENAME CONSTRAINT {old} TO {new}")

    op.alter_column("receipts", "fuel_entry_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("receipts", sa.Column("service_entry_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_receipts_service_entry_id_service_entries"),
        "receipts",
        "service_entries",
        ["service_entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        op.f("uq_receipts_service_entry_id"), "receipts", ["service_entry_id"]
    )
    op.create_check_constraint(
        op.f("ck_receipts_one_entry"),
        "receipts",
        "num_nonnulls(fuel_entry_id, service_entry_id) = 1",
    )


def downgrade() -> None:
    """Downgrade schema. Receipts of service entries have nowhere to go and are deleted."""
    op.execute("DELETE FROM receipts WHERE service_entry_id IS NOT NULL")
    op.drop_constraint(op.f("ck_receipts_one_entry"), "receipts", type_="check")
    op.drop_constraint(op.f("uq_receipts_service_entry_id"), "receipts", type_="unique")
    op.drop_constraint(
        op.f("fk_receipts_service_entry_id_service_entries"), "receipts", type_="foreignkey"
    )
    op.drop_column("receipts", "service_entry_id")
    op.alter_column("receipts", "fuel_entry_id", existing_type=sa.Integer(), nullable=False)

    for old, new in RENAMED_CONSTRAINTS:
        op.execute(f"ALTER TABLE receipts RENAME CONSTRAINT {new} TO {old}")
    op.execute("ALTER SEQUENCE receipts_id_seq RENAME TO fuel_receipts_id_seq")
    op.rename_table("receipts", "fuel_receipts")
