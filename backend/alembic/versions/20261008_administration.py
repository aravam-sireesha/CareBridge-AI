"""Add administrators and donor_suggestions tables for the Administration module."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261008_admin"
down_revision: Union[str, Sequence[str], None] = "20260929_authflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "administrators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("designation", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_administrators_user_id"),
    )
    op.create_index("ix_administrators_user_id", "administrators", ["user_id"])

    op.create_table(
        "donor_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("need_id", sa.Integer(), sa.ForeignKey("needs.id"), nullable=False),
        sa.Column("donor_id", sa.Integer(), sa.ForeignKey("donors.id"), nullable=False),
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
        sa.UniqueConstraint("need_id", "donor_id", name="uq_donor_suggestions_need_donor"),
    )
    op.create_index("ix_donor_suggestions_need_id", "donor_suggestions", ["need_id"])
    op.create_index("ix_donor_suggestions_donor_id", "donor_suggestions", ["donor_id"])


def downgrade() -> None:
    op.drop_index("ix_donor_suggestions_donor_id", table_name="donor_suggestions")
    op.drop_index("ix_donor_suggestions_need_id", table_name="donor_suggestions")
    op.drop_table("donor_suggestions")
    op.drop_index("ix_administrators_user_id", table_name="administrators")
    op.drop_table("administrators")
