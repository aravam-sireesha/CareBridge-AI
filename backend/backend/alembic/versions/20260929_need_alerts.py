"""Add alerts for needs requiring attention."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260929na"
down_revision: Union[str, Sequence[str], None] = "20260929df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "need_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("need_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("flagged_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("review_decision", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["need_id"], ["needs.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("need_alerts")