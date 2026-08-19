"""Add encrypted per-user AI settings and analysis history.

Revision ID: 20260803_0003_ai
Revises: 20260802_0002

The revision is deliberately additive and does not alter existing users or
transactions.  It follows the partners revision so a fresh deployment has a
single, deterministic Alembic head.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260803_0003_ai"
down_revision: Union[str, Sequence[str], None] = "20260802_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_ai_configs_user_id"),
    )
    op.create_index("ix_ai_configs_user_id", "ai_configs", ["user_id"], unique=False)

    op.create_table(
        "ai_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_summary", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'fallback'"), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_reports_user_id", "ai_reports", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_reports_user_id", table_name="ai_reports")
    op.drop_table("ai_reports")
    op.drop_index("ix_ai_configs_user_id", table_name="ai_configs")
    op.drop_table("ai_configs")
