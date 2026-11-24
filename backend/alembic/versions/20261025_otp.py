"""One-time codes for account recovery (new table only).

Creates `otp_challenges`. No existing table or row is touched. Skips creation if the table already exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261025_otp"
down_revision: Union[str, Sequence[str], None] = "20261024_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "otp_challenges" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False, server_default="password_reset"),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("salt", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_otp_challenges_user_id", "otp_challenges", ["user_id"])


def downgrade() -> None:
    # Only the table this revision created. Active codes are short-lived, so nothing of lasting value is lost.
    if "otp_challenges" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_otp_challenges_user_id", table_name="otp_challenges")
        op.drop_table("otp_challenges")
