"""Role frames: organization profile and verification, richer needs, donation delivery, notifications, events,
volunteer applications and service hours, user activity flags."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_frames"
down_revision: Union[str, Sequence[str], None] = "20261009_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("notification_prefs", sa.JSON(), nullable=True))

    op.add_column("organizations", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("address", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("registration_number", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("website", sa.String(), nullable=True))
    op.add_column("organizations", sa.Column("verification_status", sa.String(), nullable=False, server_default="pending"))
    op.add_column("organizations", sa.Column("verification_note", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("verification_submitted_at", sa.DateTime(), nullable=True))
    op.add_column("organizations", sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE organizations SET verification_status = 'verified' WHERE verified = true")

    op.add_column("needs", sa.Column("title", sa.String(), nullable=True))
    op.add_column("needs", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("needs", sa.Column("required_by", sa.DateTime(), nullable=True))
    op.add_column("needs", sa.Column("location", sa.String(), nullable=True))
    op.add_column("needs", sa.Column("beneficiaries", sa.Integer(), nullable=True))
    op.add_column("needs", sa.Column("fulfilled_at", sa.DateTime(), nullable=True))
    op.add_column("needs", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("needs", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("organizations", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("organizations", sa.Column("longitude", sa.Float(), nullable=True))

    op.add_column("donations", sa.Column("kind", sa.String(), nullable=False, server_default="money"))
    op.add_column("donations", sa.Column("status", sa.String(), nullable=False, server_default="confirmed"))
    op.add_column("donations", sa.Column("delivered_at", sa.DateTime(), nullable=True))
    op.add_column("donations", sa.Column("confirmed_at", sa.DateTime(), nullable=True))
    op.add_column("donations", sa.Column("delivery_note", sa.String(), nullable=True))

    op.add_column("volunteers", sa.Column("interests", sa.Text(), nullable=True))
    op.add_column("volunteers", sa.Column("availability_slots", sa.JSON(), nullable=True))

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("emailed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("skills_needed", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_events_organization_id", "events", ["organization_id"])

    op.create_table(
        "volunteer_applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("volunteer_id", sa.Integer(), sa.ForeignKey("volunteers.id"), nullable=False),
        sa.Column("need_id", sa.Integer(), sa.ForeignKey("needs.id"), nullable=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="applied"),
        sa.Column("feedback_rating", sa.Integer(), nullable=True),
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_volunteer_applications_volunteer_id", "volunteer_applications", ["volunteer_id"])
    op.create_index("ix_volunteer_applications_need_id", "volunteer_applications", ["need_id"])
    op.create_index("ix_volunteer_applications_event_id", "volunteer_applications", ["event_id"])

    op.create_table(
        "service_hours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("volunteer_id", sa.Integer(), sa.ForeignKey("volunteers.id"), nullable=False),
        sa.Column("application_id", sa.Integer(), sa.ForeignKey("volunteer_applications.id"), nullable=True),
        sa.Column("hours", sa.Float(), nullable=False),
        sa.Column("performed_on", sa.DateTime(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("verified_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_service_hours_volunteer_id", "service_hours", ["volunteer_id"])


def downgrade() -> None:
    op.drop_index("ix_service_hours_volunteer_id", table_name="service_hours")
    op.drop_table("service_hours")
    for name in ("ix_volunteer_applications_event_id", "ix_volunteer_applications_need_id", "ix_volunteer_applications_volunteer_id"):
        op.drop_index(name, table_name="volunteer_applications")
    op.drop_table("volunteer_applications")
    op.drop_index("ix_events_organization_id", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
    for col in ("availability_slots", "interests"):
        op.drop_column("volunteers", col)
    for col in ("delivery_note", "confirmed_at", "delivered_at", "status", "kind"):
        op.drop_column("donations", col)
    for col in ("longitude", "latitude", "fulfilled_at", "beneficiaries", "location", "required_by", "description", "title"):
        op.drop_column("needs", col)
    for col in ("longitude", "latitude"):
        op.drop_column("organizations", col)
    for col in ("verified_at", "verification_submitted_at", "verification_note", "verification_status", "website", "registration_number", "address", "description"):
        op.drop_column("organizations", col)
    for col in ("notification_prefs", "last_login_at", "is_active"):
        op.drop_column("users", col)
