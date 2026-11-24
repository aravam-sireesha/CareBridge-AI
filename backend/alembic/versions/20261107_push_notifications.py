"""Web Push subscriptions and the outbound-notification log (additive: two new tables, nothing existing is altered).

* push_subscriptions: one row per device a person opted in on (endpoint unique via its sha256, keys, failure counter).
* notification_events: one row per outbound notification attempt with the PROVIDER's answer. "accepted_by_provider" is never
  presented as "delivered".

Downgrade drops only these two tables (it discards subscriptions: people would have to re-enable notifications).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261107_push_notifications"
down_revision: Union[str, Sequence[str], None] = "20261106_tracking_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "push_subscriptions" not in have:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("endpoint_hash", sa.String(64), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("p256dh", sa.String(200), nullable=False),
            sa.Column("auth", sa.String(100), nullable=False),
            sa.Column("user_agent", sa.String(200), nullable=True),
            sa.Column("failure_count", sa.Integer(), nullable=False),
            sa.Column("last_accepted_at", sa.DateTime(), nullable=True),
            sa.Column("expired_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
        op.create_index("ix_push_subscriptions_endpoint_hash", "push_subscriptions", ["endpoint_hash"], unique=True)
    if "notification_events" not in have:
        op.create_table(
            "notification_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("channel", sa.String(12), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("title", sa.String(120), nullable=True),
            sa.Column("link", sa.String(300), nullable=True),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("accepted_count", sa.Integer(), nullable=False),
            sa.Column("error_code", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_notification_events_user_id", "notification_events", ["user_id"])


def downgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "notification_events" in have:
        op.drop_index("ix_notification_events_user_id", table_name="notification_events")
        op.drop_table("notification_events")
    if "push_subscriptions" in have:
        op.drop_index("ix_push_subscriptions_endpoint_hash", table_name="push_subscriptions")
        op.drop_index("ix_push_subscriptions_user_id", table_name="push_subscriptions")
        op.drop_table("push_subscriptions")
