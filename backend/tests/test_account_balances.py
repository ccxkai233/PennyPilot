from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.accounting import _cashflow_totals, _transaction_balance_totals
from app.db import Base
from app.models import PaymentMethod, Transaction, User


def test_transaction_balance_totals_include_cashflows_and_both_transfer_sides():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="balance-test", password_hash="hash")
    db.add(user)
    db.flush()
    cash = PaymentMethod(user_id=user.id, name="微信", account_role="cash")
    liability = PaymentMethod(user_id=user.id, name="京东白条", account_role="liability", track_balance=True)
    investment = PaymentMethod(user_id=user.id, name="证券账户", account_role="investment", track_balance=True)
    db.add_all([cash, liability, investment])
    db.flush()
    occurred_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    db.add_all(
        [
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, direction="income", amount_cents=10_000),
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, direction="expense", amount_cents=2_500),
            Transaction(user_id=user.id, payment_method_id=liability.id, occurred_at=occurred_at, direction="expense", amount_cents=5_000),
            Transaction(user_id=user.id, payment_method_id=cash.id, transfer_payment_method_id=liability.id, occurred_at=occurred_at, kind="transfer", direction="expense", amount_cents=1_000),
            Transaction(user_id=user.id, payment_method_id=cash.id, transfer_payment_method_id=investment.id, occurred_at=occurred_at, kind="transfer", direction="expense", amount_cents=2_000),
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, direction="income", amount_cents=99_999, status="voided"),
        ]
    )
    db.commit()

    totals = _transaction_balance_totals(db, user.id)

    assert totals[cash.id] == 4_500
    assert totals[liability.id] == 4_000
    assert totals[investment.id] == 2_000



def test_cashflow_totals_exclude_transfers_and_voided_entries():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="totals-test", password_hash="hash")
    other = User(username="totals-other", password_hash="hash")
    db.add_all([user, other])
    db.flush()
    cash = PaymentMethod(user_id=user.id, name="微信", account_role="cash")
    other_cash = PaymentMethod(user_id=other.id, name="支付宝", account_role="cash")
    db.add_all([cash, other_cash])
    db.flush()
    occurred_at = datetime(2026, 8, 3, tzinfo=timezone.utc)
    db.add_all(
        [
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, direction="income", amount_cents=10_000),
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, direction="income", amount_cents=3_000),
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, direction="expense", amount_cents=2_500),
            # Transfers and voided rows must not count toward totals.
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, kind="transfer", direction="expense", amount_cents=1_000),
            Transaction(user_id=user.id, payment_method_id=cash.id, occurred_at=occurred_at, direction="income", amount_cents=99_999, status="voided"),
            # Another tenant's rows must stay invisible.
            Transaction(user_id=other.id, payment_method_id=other_cash.id, occurred_at=occurred_at, direction="expense", amount_cents=7_000),
        ]
    )
    db.commit()

    totals = _cashflow_totals(db, user.id)

    assert totals.income_cents == 13_000
    assert totals.expense_cents == 2_500
    assert totals.income_count == 2
    assert totals.expense_count == 1


def test_cashflow_totals_default_to_zero_for_empty_history():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="totals-empty", password_hash="hash")
    db.add(user)
    db.commit()

    totals = _cashflow_totals(db, user.id)

    assert totals.income_cents == 0
    assert totals.expense_cents == 0
    assert totals.income_count == 0
    assert totals.expense_count == 0
