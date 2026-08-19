"""Enable balance tracking for every funds account.

Revision ID: 20260807_0009_balances
Revises: 20260806_0008_ai_fallback_config

Legacy cash accounts did not maintain ``current_balance_cents``. Before
enabling tracking, backfill their zero-opening balance from every normal
cashflow and both sides of internal transfers. Existing tracked balances are
left untouched because they may include a manually supplied opening balance.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260807_0009_balances"
down_revision: Union[str, Sequence[str], None] = "20260806_0008_ai_fallback_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE payment_methods AS pm
            SET current_balance_cents =
                    COALESCE(pm.current_balance_cents, 0)
                    + COALESCE(
                        (
                            SELECT SUM(
                                CASE
                                    WHEN t.kind = 'transfer' THEN -t.amount_cents
                                    WHEN pm.account_role = 'liability' THEN
                                        CASE WHEN t.direction = 'expense' THEN t.amount_cents ELSE -t.amount_cents END
                                    ELSE
                                        CASE WHEN t.direction = 'income' THEN t.amount_cents ELSE -t.amount_cents END
                                END
                            )
                            FROM transactions AS t
                            WHERE t.payment_method_id = pm.id
                              AND t.status = 'normal'
                        ),
                        0
                    )
                    + COALESCE(
                        (
                            SELECT SUM(
                                CASE WHEN pm.account_role = 'liability' THEN -t.amount_cents ELSE t.amount_cents END
                            )
                            FROM transactions AS t
                            WHERE t.transfer_payment_method_id = pm.id
                              AND t.kind = 'transfer'
                              AND t.status = 'normal'
                        ),
                        0
                    ),
                track_balance = TRUE
            WHERE pm.track_balance = FALSE
            """
        )
    )
    op.execute(
        sa.text(
            "UPDATE payment_methods SET current_balance_cents = 0 "
            "WHERE current_balance_cents IS NULL"
        )
    )
    op.alter_column(
        "payment_methods",
        "track_balance",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
    )


def downgrade() -> None:
    # Balance history cannot reveal which accounts were previously opted out.
    # Preserve the now-correct balances and only restore the legacy default.
    op.alter_column(
        "payment_methods",
        "track_balance",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )
