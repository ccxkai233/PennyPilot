"""Add financial account roles and internal transfer transactions.

Revision ID: 20260806_0007_financial_accounts
Revises: 20260805_0006_partner_website

Existing payment methods remain cash accounts.  Existing transactions remain
ordinary cashflow rows.  New transfer rows may leave ``category_id`` empty
because they are internal account movements and must not be counted as income
or expense.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0007_financial_accounts"
down_revision: Union[str, Sequence[str], None] = "20260805_0006_partner_website"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_methods",
        sa.Column(
            "account_role",
            sa.String(length=16),
            server_default="cash",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_payment_methods_account_role",
        "payment_methods",
        ["account_role"],
        unique=False,
    )
    op.add_column(
        "transactions",
        sa.Column(
            "kind",
            sa.String(length=16),
            server_default="cashflow",
            nullable=False,
        ),
    )
    op.add_column(
        "transactions",
        sa.Column("transfer_payment_method_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_transactions_kind", "transactions", ["kind"], unique=False)
    op.create_index(
        "ix_transactions_transfer_payment_method_id",
        "transactions",
        ["transfer_payment_method_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_transactions_transfer_payment_method_id_payment_methods",
        "transactions",
        "payment_methods",
        ["transfer_payment_method_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column(
        "transactions",
        "category_id",
        existing_type=sa.Integer(),
        nullable=True,
        existing_nullable=False,
    )


def downgrade() -> None:
    # Transfer rows have no legacy representation.  Delete only rows created
    # by this feature so ``category_id`` can safely become NOT NULL again.
    op.execute(sa.text("DELETE FROM transactions WHERE kind = 'transfer'"))
    op.alter_column(
        "transactions",
        "category_id",
        existing_type=sa.Integer(),
        nullable=False,
        existing_nullable=True,
    )
    op.drop_constraint(
        "fk_transactions_transfer_payment_method_id_payment_methods",
        "transactions",
        type_="foreignkey",
    )
    op.drop_index("ix_transactions_transfer_payment_method_id", table_name="transactions")
    op.drop_index("ix_transactions_kind", table_name="transactions")
    op.drop_column("transactions", "transfer_payment_method_id")
    op.drop_column("transactions", "kind")
    op.drop_index("ix_payment_methods_account_role", table_name="payment_methods")
    op.drop_column("payment_methods", "account_role")
