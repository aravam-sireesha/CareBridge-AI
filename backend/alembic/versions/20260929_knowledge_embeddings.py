"""Add local embedding storage to knowledge-base entries."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260929ke"
down_revision: Union[str, Sequence[str], None] = "20260929na"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("knowledge_base", sa.Column("embedding", sa.JSON(), nullable=True))
    op.add_column("knowledge_base", sa.Column("embedding_model", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge_base", "embedding_model")
    op.drop_column("knowledge_base", "embedding")