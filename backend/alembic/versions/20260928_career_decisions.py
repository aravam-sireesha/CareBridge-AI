"""Link career profiles to children and store one admin decision per recommendation.

Revision ID: 20260928cd
Revises: 20260928cf
Create Date: 2026-09-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260928cd"
down_revision: Union[str, Sequence[str], None] = "20260928cf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("child_profiles", sa.Column("child_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_child_profiles_child_id", "child_profiles", "children", ["child_id"], ["id"]
    )
    op.create_unique_constraint("uq_child_profiles_child_id", "child_profiles", ["child_id"])

    op.add_column("career_recommendations", sa.Column("candidates", sa.JSON(), nullable=True))
    op.add_column("career_recommendations", sa.Column("created_by", sa.Integer(), nullable=True))
    op.execute("UPDATE career_recommendations SET candidates = top_careers WHERE top_careers IS NOT NULL")
    op.create_foreign_key(
        "fk_career_recommendations_created_by", "career_recommendations", "users", ["created_by"], ["id"]
    )
    op.drop_column("career_recommendations", "top_careers")
    op.drop_column("career_recommendations", "scores")
    op.drop_column("career_recommendations", "confidence_score")

    op.add_column("recommendation_feedback", sa.Column("decision", sa.String(), nullable=True))
    op.add_column("recommendation_feedback", sa.Column("chosen_career", sa.String(), nullable=True))
    op.execute(
        "UPDATE recommendation_feedback SET decision = CASE WHEN accepted THEN 'accepted' ELSE 'rejected' END"
    )
    op.alter_column("recommendation_feedback", "decision", nullable=False)
    op.drop_column("recommendation_feedback", "accepted")
    op.create_unique_constraint(
        "uq_feedback_recommendation_id", "recommendation_feedback", ["recommendation_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_feedback_recommendation_id", "recommendation_feedback", type_="unique")
    op.add_column("recommendation_feedback", sa.Column("accepted", sa.Boolean(), nullable=True))
    op.execute(
        "UPDATE recommendation_feedback SET accepted = CASE WHEN decision = 'accepted' THEN TRUE ELSE FALSE END"
    )
    op.alter_column("recommendation_feedback", "accepted", nullable=False)
    op.drop_column("recommendation_feedback", "chosen_career")
    op.drop_column("recommendation_feedback", "decision")

    op.add_column("career_recommendations", sa.Column("confidence_score", sa.Float(), nullable=True))
    op.add_column("career_recommendations", sa.Column("scores", sa.JSON(), nullable=True))
    op.add_column("career_recommendations", sa.Column("top_careers", sa.JSON(), nullable=True))
    op.execute("UPDATE career_recommendations SET top_careers = candidates WHERE candidates IS NOT NULL")
    op.drop_constraint("fk_career_recommendations_created_by", "career_recommendations", type_="foreignkey")
    op.drop_column("career_recommendations", "created_by")
    op.drop_column("career_recommendations", "candidates")

    op.drop_constraint("uq_child_profiles_child_id", "child_profiles", type_="unique")
    op.drop_constraint("fk_child_profiles_child_id", "child_profiles", type_="foreignkey")
    op.drop_column("child_profiles", "child_id")