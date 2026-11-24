"""Volunteer timezone, transport mode and declared carrying capacity; optional delivery weight (additive only).

All new columns are nullable, so existing volunteers and deliveries are unchanged ("not stated"). Existing free-text
availability is NOT converted: volunteers confirm suggested slots themselves. Each add is skipped if the column already exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261028_availability"
down_revision: Union[str, Sequence[str], None] = "20261027_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    volunteers = _existing("volunteers")
    if "availability_timezone" not in volunteers:
        op.add_column("volunteers", sa.Column("availability_timezone", sa.String(), nullable=True))
    if "transport_mode" not in volunteers:
        op.add_column("volunteers", sa.Column("transport_mode", sa.String(), nullable=True))
    if "carry_capacity_kg" not in volunteers:
        op.add_column("volunteers", sa.Column("carry_capacity_kg", sa.Float(), nullable=True))
    if "estimated_weight_kg" not in _existing("delivery_tasks"):
        op.add_column("delivery_tasks", sa.Column("estimated_weight_kg", sa.Float(), nullable=True))


def downgrade() -> None:
    # Only the columns this revision adds. Dropping them discards declared capacities and timezones.
    if "estimated_weight_kg" in _existing("delivery_tasks"):
        op.drop_column("delivery_tasks", "estimated_weight_kg")
    volunteers = _existing("volunteers")
    for name in ("carry_capacity_kg", "transport_mode", "availability_timezone"):
        if name in volunteers:
            op.drop_column("volunteers", name)
