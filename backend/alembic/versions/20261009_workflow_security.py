"""Workflow and security: resources, allocations, audit log, lockout and two-step verification columns."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_workflow"
down_revision: Union[str, Sequence[str], None] = "20261008_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))

    op.add_column("administrators", sa.Column("totp_secret", sa.String(), nullable=True))
    op.add_column("administrators", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("administrators", sa.Column("totp_last_step", sa.Integer(), nullable=True))
    op.add_column("administrators", sa.Column("recovery_codes", sa.JSON(), nullable=True))

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_email", sa.String(), nullable=True),
        sa.Column("actor_role", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    op.create_table(
        "resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="material"),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("quantity_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="available"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_resources_organization_id", "resources", ["organization_id"])

    op.create_table(
        "resource_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("need_id", sa.Integer(), sa.ForeignKey("needs.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("proposed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_resource_allocations_resource_id", "resource_allocations", ["resource_id"])
    op.create_index("ix_resource_allocations_need_id", "resource_allocations", ["need_id"])

    op.create_table(
        "volunteer_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("need_id", sa.Integer(), sa.ForeignKey("needs.id"), nullable=False),
        sa.Column("volunteer_id", sa.Integer(), sa.ForeignKey("volunteers.id"), nullable=False),
        sa.Column("fit_score", sa.Float(), nullable=False),
        sa.Column("urgency_score", sa.Float(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("rank_in_need", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="suggested"),
        sa.Column("generated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("need_id", "volunteer_id", name="uq_volunteer_suggestions_need_volunteer"),
    )
    op.create_index("ix_volunteer_suggestions_need_id", "volunteer_suggestions", ["need_id"])
    op.create_index("ix_volunteer_suggestions_volunteer_id", "volunteer_suggestions", ["volunteer_id"])


def downgrade() -> None:
    op.drop_index("ix_volunteer_suggestions_volunteer_id", table_name="volunteer_suggestions")
    op.drop_index("ix_volunteer_suggestions_need_id", table_name="volunteer_suggestions")
    op.drop_table("volunteer_suggestions")
    for name in ("ix_resource_allocations_need_id", "ix_resource_allocations_resource_id"):
        op.drop_index(name, table_name="resource_allocations")
    op.drop_table("resource_allocations")
    op.drop_index("ix_resources_organization_id", table_name="resources")
    op.drop_table("resources")
    for name in ("ix_audit_logs_created_at", "ix_audit_logs_action", "ix_audit_logs_actor_user_id"):
        op.drop_index(name, table_name="audit_logs")
    op.drop_table("audit_logs")
    for col in ("recovery_codes", "totp_last_step", "totp_enabled", "totp_secret"):
        op.drop_column("administrators", col)
    for col in ("password_changed_at", "locked_until", "failed_login_count"):
        op.drop_column("users", col)
