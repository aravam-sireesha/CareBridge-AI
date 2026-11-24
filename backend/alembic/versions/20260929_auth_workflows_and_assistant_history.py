"""Persist account profiles, password resets, and assistant history."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_authflow"
down_revision: Union[str, Sequence[str], None] = "20260929ke"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True))
    op.add_column("users", sa.Column("donor_id", sa.Integer(), sa.ForeignKey("donors.id"), nullable=True))
    op.add_column("users", sa.Column("volunteer_id", sa.Integer(), sa.ForeignKey("volunteers.id"), nullable=True))
    op.add_column("donors", sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True))
    op.add_column("volunteers", sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True))
    op.create_index("ix_donors_organization_id", "donors", ["organization_id"])
    op.create_index("ix_volunteers_organization_id", "volunteers", ["organization_id"])
    op.add_column("knowledge_base", sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True))
    op.create_index("ix_knowledge_base_organization_id", "knowledge_base", ["organization_id"])
    op.add_column("matches", sa.Column("reasons", sa.JSON(), nullable=True))
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_assistant_messages_user_id", "assistant_messages", ["user_id"])
    op.create_index("ix_assistant_messages_organization_id", "assistant_messages", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_organization_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_user_id", table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_knowledge_base_organization_id", table_name="knowledge_base")
    op.drop_column("knowledge_base", "organization_id")
    op.drop_column("matches", "reasons")
    op.drop_index("ix_volunteers_organization_id", table_name="volunteers")
    op.drop_index("ix_donors_organization_id", table_name="donors")
    op.drop_column("volunteers", "organization_id")
    op.drop_column("donors", "organization_id")
    op.drop_column("users", "volunteer_id")
    op.drop_column("users", "donor_id")
    op.drop_column("users", "organization_id")
    op.drop_column("users", "token_version")
