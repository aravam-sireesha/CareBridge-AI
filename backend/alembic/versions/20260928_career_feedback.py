"""Add career profile history and recommendation feedback.

Revision ID: 20260928cf
Revises: d1c17fb377c8
Create Date: 2026-09-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260928cf"
down_revision: Union[str, Sequence[str], None] = "d1c17fb377c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "child_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("career_recommendations", sa.Column("profile_id", sa.Integer(), nullable=True))
    op.add_column("career_recommendations", sa.Column("top_careers", sa.JSON(), nullable=True))
    op.add_column("career_recommendations", sa.Column("scores", sa.JSON(), nullable=True))
    op.add_column("career_recommendations", sa.Column("model_version", sa.String(), nullable=True))
    op.add_column(
        "career_recommendations",
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_foreign_key(
        "fk_career_recommendations_profile_id",
        "career_recommendations",
        "child_profiles",
        ["profile_id"],
        ["id"],
    )
    op.create_table(
        "recommendation_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recommendation_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["career_recommendations.id"], name="fk_feedback_recommendation_id"
        ),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], name="fk_feedback_admin_id"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("recommendation_feedback")
    op.drop_constraint("fk_career_recommendations_profile_id", "career_recommendations", type_="foreignkey")
    op.drop_column("career_recommendations", "created_at")
    op.drop_column("career_recommendations", "model_version")
    op.drop_column("career_recommendations", "scores")
    op.drop_column("career_recommendations", "top_careers")
    op.drop_column("career_recommendations", "profile_id")
    op.drop_table("child_profiles")