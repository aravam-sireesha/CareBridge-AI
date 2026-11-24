"""Mobile-number verification at registration: three nullable columns on users and a unique index (additive only).

No existing account changes: the columns start NULL, and NULL means "no number" / "not pending", so nobody is locked out when
phone verification is switched on later. Downgrade drops only what this revision adds (it discards stored mobile numbers).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261105_phone_verification"
down_revision: Union[str, Sequence[str], None] = "20261029_email_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table: str) -> set[str]:
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str):
    """Index names, or None when the inspector cannot list them (then the index step is attempted unconditionally)."""
    try:
        return {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}
    except AttributeError:
        return None


def upgrade() -> None:
    cols = _columns("users")
    added_phone = "phone_e164" not in cols
    if added_phone:
        op.add_column("users", sa.Column("phone_e164", sa.String(), nullable=True))
    if "phone_verification_pending" not in cols:
        op.add_column("users", sa.Column("phone_verification_pending", sa.Boolean(), nullable=True))
    if "phone_verified_at" not in cols:
        op.add_column("users", sa.Column("phone_verified_at", sa.DateTime(), nullable=True))
    existing = _indexes("users")
    # If indexes cannot be listed, only a freshly added column can be missing its index.
    if (existing is None and added_phone) or (existing is not None and "ix_users_phone_e164" not in existing):
        op.create_index("ix_users_phone_e164", "users", ["phone_e164"], unique=True)


def downgrade() -> None:
    cols = _columns("users")
    existing = _indexes("users")
    if (existing is None and "phone_e164" in cols) or (existing is not None and "ix_users_phone_e164" in existing):
        op.drop_index("ix_users_phone_e164", table_name="users")
    for name in ("phone_verified_at", "phone_verification_pending", "phone_e164"):
        if name in cols:
            op.drop_column("users", name)
