"""Add batch execution metadata.

Revision ID: 20261101_0002
Revises: 20261101_0001
Create Date: 2026-11-01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261101_0002"
down_revision = "20261101_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="RUNNING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'CANCELLED')",
            name="ck_batches_status",
        ),
    )

    op.add_column(
        "submissions",
        sa.Column("batch_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_submissions_batch_id_batches",
        "submissions",
        "batches",
        ["batch_id"],
        ["id"],
    )
    op.add_column(
        "submissions",
        sa.Column("repeat_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "submissions",
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "submissions",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_submissions_batch_id", "submissions", ["batch_id"])
    op.create_index("ix_submissions_batch_status", "submissions", ["batch_id", "status"])
    op.create_index("ix_submissions_batch_verdict", "submissions", ["batch_id", "verdict"])
    op.create_index("ix_submissions_user_created", "submissions", ["user_id", "created_at"])

    op.add_column(
        "run_results",
        sa.Column("concurrent_containers", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run_results", "concurrent_containers")
    op.drop_index("ix_submissions_user_created", table_name="submissions")
    op.drop_index("ix_submissions_batch_verdict", table_name="submissions")
    op.drop_index("ix_submissions_batch_status", table_name="submissions")
    op.drop_index("ix_submissions_batch_id", table_name="submissions")
    op.drop_column("submissions", "started_at")
    op.drop_column("submissions", "queued_at")
    op.drop_column("submissions", "repeat_index")
    op.drop_constraint("fk_submissions_batch_id_batches", "submissions", type_="foreignkey")
    op.drop_column("submissions", "batch_id")
    op.drop_table("batches")
