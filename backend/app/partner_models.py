"""SQLAlchemy models for supplier/customer current accounts.

The core ``transactions.partner_id`` column predates this module and is
intentionally left as a nullable integer for backwards compatibility.  The
new tables use explicit foreign keys and keep a denormalised ``user_id`` on
ledger rows so every query can enforce tenant ownership without relying on a
caller supplied partner id.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Partner(Base):
    """A supplier or customer account owned by one user."""

    __tablename__ = "partners"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "name", name="uq_partners_user_type_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # ``type`` is the public/API name used by the plan (supplier/customer).
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # website is the canonical profile URL. Keep the legacy email column for
    # existing databases/clients; it is intentionally not renamed or dropped
    # so historical email values remain recoverable.
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    prepaid_balance_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    credit_limit_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    credit_used_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active", index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    @property
    def credit_remaining_cents(self) -> int:
        """Available credit, exposed for ORM/Pydantic response validation."""

        return max((self.credit_limit_cents or 0) - (self.credit_used_cents or 0), 0)


class PartnerLedgerEntry(Base):
    """An immutable/auditable balance movement for a partner.

    ``amount_cents`` is positive for all movement types except
    ``limit_adjust``, where a negative value lowers the credit limit.  The
    three before/after pairs capture the complete account state, while the
    generic balance pair makes list views convenient and preserves the
    terminology used in the product plan.
    """

    __tablename__ = "partner_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    partner_id: Mapped[int] = mapped_column(
        ForeignKey("partners.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_before_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prepaid_before_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prepaid_after_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_limit_before_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_limit_after_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_used_before_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_used_after_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reversal_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("partner_ledger.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reversed_entry_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal", server_default="normal", index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
