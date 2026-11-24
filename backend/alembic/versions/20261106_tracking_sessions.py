"""Live-tracking sessions and the opt-in movement trail (additive only: two new tables, nothing existing is altered).

* tracking_sessions: one row per consented period of location sharing for one delivery (purpose, consent wording version,
  whether a trail may be kept, expiry, pause/stop times, last sequence number for duplicate protection).
* location_history: trail points, written ONLY for sessions whose volunteer opted in. Unique (session_id, seq) makes a
  re-sent point harmless. The retention job deletes rows older than LOCATION_RETENTION_DAYS.

Downgrade drops only these two tables (it discards stored trails and session records; take a backup first).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261106_tracking_sessions"
down_revision: Union[str, Sequence[str], None] = "20261105_phone_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "tracking_sessions" not in have:
        op.create_table(
            "tracking_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(36), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("delivery_tasks.id"), nullable=False),
            sa.Column("volunteer_id", sa.Integer(), sa.ForeignKey("volunteers.id"), nullable=False),
            sa.Column("status", sa.String(10), nullable=False),
            sa.Column("purpose", sa.String(60), nullable=False),
            sa.Column("consent_version", sa.String(20), nullable=False),
            sa.Column("consented_at", sa.DateTime(), nullable=False),
            sa.Column("retain_history", sa.Boolean(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("paused_at", sa.DateTime(), nullable=True),
            sa.Column("stopped_at", sa.DateTime(), nullable=True),
            sa.Column("last_seq", sa.Integer(), nullable=False),
            sa.Column("stale_notified_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_tracking_sessions_public_id", "tracking_sessions", ["public_id"], unique=True)
        op.create_index("ix_tracking_sessions_task_id", "tracking_sessions", ["task_id"])
        op.create_index("ix_tracking_sessions_volunteer_id", "tracking_sessions", ["volunteer_id"])
    if "location_history" not in have:
        op.create_table(
            "location_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("tracking_sessions.id"), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("delivery_tasks.id"), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("latitude", sa.Float(), nullable=False),
            sa.Column("longitude", sa.Float(), nullable=False),
            sa.Column("accuracy_m", sa.Float(), nullable=True),
            sa.Column("heading", sa.Float(), nullable=True),
            sa.Column("speed_mps", sa.Float(), nullable=True),
            sa.Column("client_time", sa.DateTime(), nullable=True),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("flagged", sa.Boolean(), nullable=False),
            sa.UniqueConstraint("session_id", "seq", name="uq_location_history_session_seq"),
        )
        op.create_index("ix_location_history_session_id", "location_history", ["session_id"])
        op.create_index("ix_location_history_task_id", "location_history", ["task_id"])
        op.create_index("ix_location_history_recorded_at", "location_history", ["recorded_at"])


def downgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "location_history" in have:
        for name in ("recorded_at", "task_id", "session_id"):
            op.drop_index(f"ix_location_history_{name}", table_name="location_history")
        op.drop_table("location_history")
    if "tracking_sessions" in have:
        for name in ("volunteer_id", "task_id", "public_id"):
            op.drop_index(f"ix_tracking_sessions_{name}", table_name="tracking_sessions")
        op.drop_table("tracking_sessions")
