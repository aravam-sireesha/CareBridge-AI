"""Background-job log, private document metadata, and payment records (additive: four new tables, nothing existing is altered).

* background_jobs: durable status log for queued work (the queue itself is in Redis).
* stored_documents: metadata for files in private object storage; review_status makes "uploaded" and "verified" different things.
* payment_transactions / payment_events: Razorpay orders and processed webhook ids (unique id = idempotent webhooks).
Payments stay disabled by configuration; creating these tables does not enable them.

Downgrade drops only these tables (it discards the job log, document records, and payment records: take a backup first. Dropping
stored_documents does NOT delete the files in object storage).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261108_jobs_storage_payments"
down_revision: Union[str, Sequence[str], None] = "20261107_push_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "background_jobs" not in have:
        op.create_table(
            "background_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(60), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_background_jobs_job_id", "background_jobs", ["job_id"], unique=True)
        op.create_index("ix_background_jobs_name", "background_jobs", ["name"])
    if "stored_documents" not in have:
        op.create_table(
            "stored_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("owner_type", sa.String(16), nullable=False),
            sa.Column("owner_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("object_key", sa.String(200), nullable=False),
            sa.Column("original_name", sa.String(120), nullable=True),
            sa.Column("content_type", sa.String(60), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("review_status", sa.String(12), nullable=False),
            sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("review_note", sa.String(300), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_stored_documents_object_key", "stored_documents", ["object_key"], unique=True)
    if "payment_transactions" not in have:
        op.create_table(
            "payment_transactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
            sa.Column("razorpay_order_id", sa.String(40), nullable=False),
            sa.Column("razorpay_payment_id", sa.String(40), nullable=True),
            sa.Column("receipt", sa.String(40), nullable=False),
            sa.Column("amount_paise", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_payment_transactions_user_id", "payment_transactions", ["user_id"])
        op.create_index("ix_payment_transactions_razorpay_order_id", "payment_transactions", ["razorpay_order_id"], unique=True)
        op.create_index("ix_payment_transactions_razorpay_payment_id", "payment_transactions", ["razorpay_payment_id"], unique=True)
        op.create_index("ix_payment_transactions_receipt", "payment_transactions", ["receipt"], unique=True)
    if "payment_events" not in have:
        op.create_table(
            "payment_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.String(80), nullable=False),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("razorpay_order_id", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_payment_events_event_id", "payment_events", ["event_id"], unique=True)


def downgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "payment_events" in have:
        op.drop_index("ix_payment_events_event_id", table_name="payment_events"); op.drop_table("payment_events")
    if "payment_transactions" in have:
        for n in ("receipt", "razorpay_payment_id", "razorpay_order_id", "user_id"):
            op.drop_index(f"ix_payment_transactions_{n}", table_name="payment_transactions")
        op.drop_table("payment_transactions")
    if "stored_documents" in have:
        op.drop_index("ix_stored_documents_object_key", table_name="stored_documents"); op.drop_table("stored_documents")
    if "background_jobs" in have:
        op.drop_index("ix_background_jobs_name", table_name="background_jobs"); op.drop_index("ix_background_jobs_job_id", table_name="background_jobs"); op.drop_table("background_jobs")
