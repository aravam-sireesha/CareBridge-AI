"""Optional location for donors and volunteers (additive only).

Adds nullable columns, so every existing row keeps its data and simply has "no location shared" (NULL).
Nothing is dropped, rewritten or backfilled. Adding a nullable column without a default is a metadata-only
change in PostgreSQL, so it is fast and does not lock the table for long.

The upgrade skips any column that already exists, so running it against a database where someone added a
column by hand does not fail half-way.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261024_locations"
down_revision: Union[str, Sequence[str], None] = "20261023_llm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    donors = _existing("donors")
    if "latitude" not in donors:
        op.add_column("donors", sa.Column("latitude", sa.Float(), nullable=True))
    if "longitude" not in donors:
        op.add_column("donors", sa.Column("longitude", sa.Float(), nullable=True))
    if "location_updated_at" not in donors:
        op.add_column("donors", sa.Column("location_updated_at", sa.DateTime(), nullable=True))

    volunteers = _existing("volunteers")
    if "latitude" not in volunteers:
        op.add_column("volunteers", sa.Column("latitude", sa.Float(), nullable=True))
    if "longitude" not in volunteers:
        op.add_column("volunteers", sa.Column("longitude", sa.Float(), nullable=True))
    if "service_radius_km" not in volunteers:
        op.add_column("volunteers", sa.Column("service_radius_km", sa.Float(), nullable=True))
    if "location_updated_at" not in volunteers:
        op.add_column("volunteers", sa.Column("location_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Only the columns this revision adds. Dropping them discards the locations people chose to share.
    volunteers = _existing("volunteers")
    for name in ("location_updated_at", "service_radius_km", "longitude", "latitude"):
        if name in volunteers:
            op.drop_column("volunteers", name)
    donors = _existing("donors")
    for name in ("location_updated_at", "longitude", "latitude"):
        if name in donors:
            op.drop_column("donors", name)
