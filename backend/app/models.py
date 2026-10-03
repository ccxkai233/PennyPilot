from datetime import date, datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

# Import the phase-three models here so ``Base.metadata`` (and Alembic's
# autogenerate target) includes them.  The classes remain in a separate module
# to keep the core model file stable while AI/partner features evolve.
from .partner_models import Partner, PartnerLedgerEntry  # noqa: F401,E402
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
class SessionToken(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Category(Base):
    """A user-defined income or expense category.

    ``user_id`` is nullable for backwards compatibility with databases created
    by the first prototype (which did not have per-user bookkeeping tables).
    All records created through the API are scoped to the authenticated user.
    """

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "name", "direction", name="uq_categories_user_name_direction"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PaymentMethod(Base):
    """A payment/collection account with a maintained running balance.

    ``account_role`` controls how balance movements are interpreted:

    - ``cash``: real cash/payment accounts such as Alipay, WeChat, bank, paper cash.
    - ``liability``: credit cards, Huabei, Baitiao, loans; the balance is debt owed.
    - ``investment``: securities/funds/other investment holdings.
    """

    __tablename__ = "payment_methods"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_payment_methods_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="cash", server_default="cash", index=True
    )
    track_balance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    current_balance_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Transaction(Base):
    """A normal income/expense entry or an internal account transfer.

    Entries are never physically deleted.  A void operation changes ``status``
    to ``voided`` and stores when/why it happened; the linked payment method's
    tracked balance is reversed in the same database transaction.  ``kind`` is
    ``cashflow`` for ordinary income/expense and ``transfer`` for internal
    account movements such as credit-card repayment or moving money into an
    investment account.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="cashflow", server_default="cashflow", index=True
    )
    direction: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    payment_method_id: Mapped[int] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    transfer_payment_method_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_methods.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Partners are introduced in the next phase.  Keep this as an indexed
    # nullable id for now so the core API can accept/return the association
    # without requiring the partners table to exist yet.
    partner_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="normal", server_default="normal", index=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AIConfig(Base):
    """Per-user AI provider settings (primary and fallback channel).

    The API key is stored only as authenticated ciphertext.  ``base_url`` and
    ``model`` are intentionally kept separate from ``users`` so introducing AI
    support does not require rewriting existing user rows or making a key part
    of the normal user response schema.
    """

    __tablename__ = "ai_configs"
    __table_args__ = (UniqueConstraint("user_id", name="uq_ai_configs_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fallback_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    encrypted_fallback_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "openai" | "anthropic" | "gemini"; NULL keeps the deployment default.
    api_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fallback_api_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AIReport(Base):
    """Bounded AI analysis history, scoped to one authenticated user."""

    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_summary: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="fallback", server_default="fallback")
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIConversation(Base):
    """A thread of ledger questions and answers on the transactions page."""

    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AIConversationMessage(Base):
    """One turn of a conversation, with the tool steps and change proposals it produced."""

    __tablename__ = "ai_conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [{name, summary, result}] tool calls shown under the answer
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # [{type, status, before, after, ...}] change proposals awaiting confirmation
    proposals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    report_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    warning: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DailySnapshot(Base):
    """Immutable (outside an explicit recalculation) daily settlement.

    A snapshot is scoped to one user and one Beijing (Asia/Shanghai)
    settlement date.  Timestamp columns remain UTC instants in the API/DB.
    account columns deliberately use JSON rather than a second set of
    relational tables: they are a point-in-time report and must remain stable
    even when a partner is later renamed or archived.  ``account_balances``
    and ``account_changes`` contain denormalised partner ids/names plus the
    three balance dimensions used by the current-account module.
    """

    __tablename__ = "daily_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "settlement_date", name="uq_daily_snapshots_user_date"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    settled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    income_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expense_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_assets_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_balances: Mapped[list] = mapped_column(JSON, nullable=False)
    account_changes: Mapped[list] = mapped_column(JSON, nullable=False)
    # A normal ``run`` never mutates an existing row.  Recalculation is the
    # only path that updates a snapshot and leaves this audit marker behind.
    is_recalculated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    recalculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Feedback(Base):
    """A free-form feedback/bug-report entry submitted by a user.

    Feedback is append-only: users can submit and review their own
    submissions from anywhere in the app, but there is no update/delete
    endpoint, so the history a user sees always matches what was sent.
    """

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(
        String(16), nullable=False, default="other", server_default="other", index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
