"""Add immutable daily settlement snapshots.

Revision ID: 20260804_0004_settlements
Revises: 20260803_0003_ai

The snapshot is intentionally a denormalised report.  Partner and transaction
history remains the source of truth; an explicit recalculation is the only
operation that may refresh an existing snapshot.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260804_0004_settlements"
down_revision: Union[str, Sequence[str], None] = "20260803_0003_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column(
            "settled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("income_cents", sa.BigInteger(), nullable=False),
        sa.Column("expense_cents", sa.BigInteger(), nullable=False),
        sa.Column("net_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_assets_cents", sa.BigInteger(), nullable=False),
        sa.Column("account_balances", sa.JSON(), nullable=False),
        sa.Column("account_changes", sa.JSON(), nullable=False),
        sa.Column(
            "is_recalculated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("recalculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "settlement_date", name="uq_daily_snapshots_user_date"
        ),
    )
    op.create_index(
        "ix_daily_snapshots_user_id", "daily_snapshots", ["user_id"], unique=False
    )
    op.create_index(
        "ix_daily_snapshots_settlement_date",
        "daily_snapshots",
        ["settlement_date"],
        unique=False,
    )
    op.create_index(
        "ix_daily_snapshots_is_recalculated",
        "daily_snapshots",
        ["is_recalculated"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_daily_snapshots_is_recalculated", table_name="daily_snapshots")
    op.drop_index("ix_daily_snapshots_settlement_date", table_name="daily_snapshots")
    op.drop_index("ix_daily_snapshots_user_id", table_name="daily_snapshots")
    op.drop_table("daily_snapshots")
