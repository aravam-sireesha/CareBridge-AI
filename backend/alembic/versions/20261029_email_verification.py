"""E-mail verification at registration: two nullable columns on users (additive only).

No existing account changes: both columns start NULL, and NULL means "not pending", so nobody is locked out when verification is
switched on later. No data is backfilled or rewritten.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261029_email_verification"
down_revision: Union[str, Sequence[str], None] = "20261028_availability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    users = _existing("users")
    if "email_verification_pending" not in users:
        op.add_column("users", sa.Column("email_verification_pending", sa.Boolean(), nullable=True))
    if "email_verified_at" not in users:
        op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Only the columns this revision adds. Dropping them discards who verified their address and when.
    users = _existing("users")
    for name in ("email_verified_at", "email_verification_pending"):
        if name in users:
            op.drop_column("users", name)
