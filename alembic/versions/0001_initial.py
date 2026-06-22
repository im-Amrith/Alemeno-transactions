"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


job_status_enum = postgresql.ENUM(
    "pending", "processing", "completed", "failed", name="jobstatus"
)


def upgrade() -> None:
    job_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "processing", "completed", "failed",
                name="jobstatus", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("row_count_raw", sa.Integer(), nullable=True),
        sa.Column("row_count_clean", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("txn_id", sa.String(), nullable=True),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("merchant", sa.String(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("account_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_anomaly", sa.Boolean(), server_default=sa.false()),
        sa.Column("anomaly_reason", sa.String(), nullable=True),
        sa.Column("llm_category", sa.String(), nullable=True),
        sa.Column("llm_raw_response", sa.Text(), nullable=True),
        sa.Column("llm_failed", sa.Boolean(), server_default=sa.false()),
    )
    op.create_index("ix_transactions_job_id", "transactions", ["job_id"])

    op.create_table(
        "job_summaries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("total_spend_inr", sa.Float(), server_default="0"),
        sa.Column("total_spend_usd", sa.Float(), server_default="0"),
        sa.Column("top_merchants", sa.JSON(), nullable=True),
        sa.Column("anomaly_count", sa.Integer(), server_default="0"),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("job_summaries")
    op.drop_index("ix_transactions_job_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("jobs")
    job_status_enum.drop(op.get_bind(), checkfirst=True)
