"""Add supplier/customer current accounts and auditable ledger.

Revision ID: 20260802_0002
Revises: 20260802_0001
Create Date: 2026-08-02

The existing nullable ``transactions.partner_id`` column is intentionally not
changed to a foreign key here: old prototype databases may contain arbitrary
legacy ids.  New ledger rows reference the canonical ``partners`` table.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260802_0002"
down_revision: Union[str, Sequence[str], None] = "20260802_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "partners",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("contact", sa.String(length=500), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("prepaid_balance_cents", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("credit_limit_cents", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("credit_used_cents", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "type", "name", name="uq_partners_user_type_name"),
    )
    op.create_index("ix_partners_user_id", "partners", ["user_id"], unique=False)
    op.create_index("ix_partners_type", "partners", ["type"], unique=False)
    op.create_index("ix_partners_status", "partners", ["status"], unique=False)

    op.create_table(
        "partner_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("partner_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("entry_type", sa.String(length=24), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("balance_before_cents", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("prepaid_before_cents", sa.BigInteger(), nullable=False),
        sa.Column("prepaid_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("credit_limit_before_cents", sa.BigInteger(), nullable=False),
        sa.Column("credit_limit_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("credit_used_before_cents", sa.BigInteger(), nullable=False),
        sa.Column("credit_used_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("reversal_of_id", sa.Integer(), nullable=True),
        sa.Column("reversed_entry_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'normal'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["partner_id"], ["partners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["partner_ledger.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_partner_ledger_user_id", "partner_ledger", ["user_id"], unique=False)
    op.create_index("ix_partner_ledger_partner_id", "partner_ledger", ["partner_id"], unique=False)
    op.create_index("ix_partner_ledger_occurred_at", "partner_ledger", ["occurred_at"], unique=False)
    op.create_index("ix_partner_ledger_entry_type", "partner_ledger", ["entry_type"], unique=False)
    op.create_index("ix_partner_ledger_transaction_id", "partner_ledger", ["transaction_id"], unique=False)
    op.create_index("ix_partner_ledger_reversal_of_id", "partner_ledger", ["reversal_of_id"], unique=False)
    op.create_index("ix_partner_ledger_reversed_entry_id", "partner_ledger", ["reversed_entry_id"], unique=False)
    op.create_index("ix_partner_ledger_status", "partner_ledger", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_partner_ledger_status", table_name="partner_ledger")
    op.drop_index("ix_partner_ledger_reversed_entry_id", table_name="partner_ledger")
    op.drop_index("ix_partner_ledger_reversal_of_id", table_name="partner_ledger")
    op.drop_index("ix_partner_ledger_transaction_id", table_name="partner_ledger")
    op.drop_index("ix_partner_ledger_entry_type", table_name="partner_ledger")
    op.drop_index("ix_partner_ledger_occurred_at", table_name="partner_ledger")
    op.drop_index("ix_partner_ledger_partner_id", table_name="partner_ledger")
    op.drop_index("ix_partner_ledger_user_id", table_name="partner_ledger")
    op.drop_table("partner_ledger")

    op.drop_index("ix_partners_status", table_name="partners")
    op.drop_index("ix_partners_type", table_name="partners")
    op.drop_index("ix_partners_user_id", table_name="partners")
    op.drop_table("partners")

