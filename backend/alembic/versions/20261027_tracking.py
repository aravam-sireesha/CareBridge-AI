"""Live delivery tracking: one table holding only the latest shared position per delivery (new table only)."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261027_tracking"
down_revision: Union[str, Sequence[str], None] = "20261026_deliveries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "delivery_locations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "delivery_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("delivery_tasks.id"), nullable=False),
        sa.Column("volunteer_id", sa.Integer(), sa.ForeignKey("volunteers.id"), nullable=False),
        sa.Column("consented_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_delivery_locations_task_id", "delivery_locations", ["task_id"], unique=True)


def downgrade() -> None:
    # Only the table this revision created. It holds short-lived positions, so nothing of lasting value is lost.
    if "delivery_locations" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_delivery_locations_task_id", table_name="delivery_locations")
        op.drop_table("delivery_locations")
