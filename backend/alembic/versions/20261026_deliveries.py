"""Delivery workflow tables (new tables only).

Creates `delivery_tasks` and `delivery_events`. No existing table or row is touched, so existing donations, needs and
matches keep working exactly as before. Each table is skipped if it already exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261026_deliveries"
down_revision: Union[str, Sequence[str], None] = "20261025_otp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TIMESTAMPS = ["submitted_at", "decided_at", "committed_at", "offered_at", "accepted_at", "pickup_at", "picked_up_at",
               "in_transit_at", "delivered_at", "confirmed_at", "cancelled_at", "exception_at"]


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "delivery_tasks" not in have:
        cols = [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("need_id", sa.Integer(), sa.ForeignKey("needs.id"), nullable=False),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("donor_id", sa.Integer(), sa.ForeignKey("donors.id"), nullable=False),
            sa.Column("volunteer_id", sa.Integer(), sa.ForeignKey("volunteers.id"), nullable=True),
            sa.Column("match_id", sa.Integer(), sa.ForeignKey("matches.id"), nullable=True),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("item_description", sa.String(300)),
            sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        ]
        cols += [sa.Column(name, sa.DateTime()) for name in _TIMESTAMPS]
        cols += [
            sa.Column("decision_reason", sa.String(500)), sa.Column("delivery_note", sa.String(500)),
            sa.Column("received_quantity", sa.Integer()), sa.Column("receipt_note", sa.String(500)),
            sa.Column("cancel_reason", sa.String(500)), sa.Column("exception_reason", sa.String(500)), sa.Column("exception_from", sa.String()),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("quantity >= 1", name="ck_delivery_quantity_positive"),
        ]
        op.create_table("delivery_tasks", *cols)
        for column in ("need_id", "org_id", "donor_id", "volunteer_id", "status"):
            op.create_index(f"ix_delivery_tasks_{column}", "delivery_tasks", [column])
    if "delivery_events" not in have:
        op.create_table(
            "delivery_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("delivery_tasks.id"), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("from_status", sa.String()),
            sa.Column("to_status", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("actor_role", sa.String()),
            sa.Column("note", sa.String(500)),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_delivery_events_task_id", "delivery_events", ["task_id"])


def downgrade() -> None:
    # Only the tables this revision created. This discards delivery history, so take a backup first.
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "delivery_events" in have:
        op.drop_index("ix_delivery_events_task_id", table_name="delivery_events")
        op.drop_table("delivery_events")
    if "delivery_tasks" in have:
        for column in ("status", "volunteer_id", "donor_id", "org_id", "need_id"):
            op.drop_index(f"ix_delivery_tasks_{column}", table_name="delivery_tasks")
        op.drop_table("delivery_tasks")
