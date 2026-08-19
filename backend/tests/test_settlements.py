from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Category, DailySnapshot, PaymentMethod, Partner, Transaction, User
from app.partners import _append_entry
from app.settlement_job import run_all_users
from app.settlements import _calculate_snapshot, generate_snapshot


UTC = timezone.utc


def _db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_snapshot_replays_backdated_partner_movements_and_totals():
    db = _db()
    user = User(username="settlement-test", password_hash="hash")
    db.add(user)
    db.flush()
    category = Category(user_id=user.id, name="销售", direction="income")
    expense_category = Category(user_id=user.id, name="进货", direction="expense")
    method = PaymentMethod(user_id=user.id, name="现金")
    partner = Partner(user_id=user.id, type="supplier", name="供应商")
    db.add_all([category, expense_category, method, partner])
    db.flush()

    def add(entry_type: str, amount: int, when: datetime):
        entry = _append_entry(
            db,
            partner,
            user_id=user.id,
            entry_type=entry_type,
            amount_cents=amount,
            occurred_at=when,
        )
        db.flush()
        return entry

    add("prepaid_in", 100, datetime(2026, 7, 1, tzinfo=UTC))
    add("prepaid_in", 100, datetime(2026, 7, 10, tzinfo=UTC))
    add("prepaid_in", 100, datetime(2026, 7, 20, tzinfo=UTC))
    # Entered last but backdated: the before/after snapshot is 300 -> 320;
    # settlement must use its signed delta at July 5, not that stale before.
    add("prepaid_in", 20, datetime(2026, 7, 5, tzinfo=UTC))

    db.add_all(
        [
            Transaction(
                user_id=user.id,
                occurred_at=datetime(2026, 7, 5, 9, tzinfo=UTC),
                direction="income",
                amount_cents=500,
                category_id=category.id,
                payment_method_id=method.id,
            ),
            Transaction(
                user_id=user.id,
                occurred_at=datetime(2026, 7, 5, 10, tzinfo=UTC),
                direction="expense",
                amount_cents=200,
                category_id=expense_category.id,
                payment_method_id=method.id,
                partner_id=partner.id,
            ),
        ]
    )
    db.commit()

    # Check more than the day containing the correction.  The earliest
    # *created* row is the zero opening baseline; replaying signed deltas in
    # occurred_at order must therefore produce 100 -> 120 -> 220 -> 320,
    # rather than treating the backdated row's insertion-time ``before``
    # snapshot (300) as the historical opening balance.
    assert _calculate_snapshot(db, user.id, datetime(2026, 7, 1).date())["account_balances"][0]["prepaid_balance_cents"] == 100
    values = _calculate_snapshot(db, user.id, datetime(2026, 7, 5).date())
    assert values["income_cents"] == 500
    assert values["expense_cents"] == 200
    assert values["net_cents"] == 300
    assert values["account_balances"][0]["prepaid_balance_cents"] == 120
    # Cash cumulative (500 - 200) + supplier prepaid (120).
    assert values["total_assets_cents"] == 420
    assert values["account_changes"][0]["prepaid_delta_cents"] == 20
    assert values["account_balances"][0]["unsettled_balance_cents"] == 120
    assert values["account_changes"][0]["unsettled_delta_cents"] == 20
    assert values["account_changes"][0]["settlement_amount_cents"] == -200
    assert values["account_changes"][0]["settlement_count"] == 1
    assert _calculate_snapshot(db, user.id, datetime(2026, 7, 10).date())["account_balances"][0]["prepaid_balance_cents"] == 220
    assert _calculate_snapshot(db, user.id, datetime(2026, 7, 20).date())["account_balances"][0]["prepaid_balance_cents"] == 320


def test_snapshot_uses_beijing_half_open_day_boundaries_and_tenant_scope():
    db = _db()
    first = User(username="boundary-first", password_hash="hash")
    second = User(username="boundary-second", password_hash="hash")
    db.add_all([first, second])
    db.flush()

    first_category = Category(user_id=first.id, name="收入", direction="income")
    first_method = PaymentMethod(user_id=first.id, name="现金")
    first_partner = Partner(user_id=first.id, type="supplier", name="甲方")
    second_category = Category(user_id=second.id, name="收入", direction="income")
    second_method = PaymentMethod(user_id=second.id, name="现金")
    second_partner = Partner(user_id=second.id, type="supplier", name="乙方")
    db.add_all(
        [
            first_category,
            first_method,
            first_partner,
            second_category,
            second_method,
            second_partner,
        ]
    )
    db.flush()

    _append_entry(
        db,
        first_partner,
        user_id=first.id,
        entry_type="prepaid_in",
        amount_cents=11,
        # 2026-07-05 Beijing day ends at 2026-07-05 16:00Z.
        occurred_at=datetime(2026, 7, 5, 15, 59, 59, 999999, tzinfo=UTC),
    )
    _append_entry(
        db,
        first_partner,
        user_id=first.id,
        entry_type="prepaid_in",
        amount_cents=17,
        # Exactly Beijing midnight belongs to the following natural day.
        occurred_at=datetime(2026, 7, 5, 16, tzinfo=UTC),
    )
    db.add(
        Transaction(
            user_id=first.id,
            occurred_at=datetime(2026, 7, 5, 15, 59, 59, 999999, tzinfo=UTC),
            direction="income",
            amount_cents=31,
            category_id=first_category.id,
            payment_method_id=first_method.id,
        )
    )
    db.add(
        Transaction(
            user_id=first.id,
            occurred_at=datetime(2026, 7, 6, tzinfo=UTC),
            direction="income",
            amount_cents=47,
            category_id=first_category.id,
            payment_method_id=first_method.id,
        )
    )
    # A second user's data must never enter the first user's snapshot, even
    # when both users settle the same Beijing date.
    _append_entry(
        db,
        second_partner,
        user_id=second.id,
        entry_type="prepaid_in",
        amount_cents=999,
        occurred_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
    )
    db.add(
        Transaction(
            user_id=second.id,
            occurred_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
            direction="income",
            amount_cents=888,
            category_id=second_category.id,
            payment_method_id=second_method.id,
        )
    )
    db.commit()

    first_day = _calculate_snapshot(db, first.id, datetime(2026, 7, 5).date())
    assert first_day["income_cents"] == 31
    assert first_day["account_balances"][0]["prepaid_balance_cents"] == 11
    assert [item["name"] for item in first_day["account_balances"]] == ["甲方"]
    next_day = _calculate_snapshot(db, first.id, datetime(2026, 7, 6).date())
    assert next_day["income_cents"] == 47
    assert next_day["account_balances"][0]["prepaid_balance_cents"] == 28


def test_recalculate_refreshes_existing_snapshot_but_normal_run_stays_immutable():
    db = _db()
    user = User(username="recalc-test", password_hash="hash")
    category = Category(user_id=None, name="收入", direction="income")
    db.add_all([user, category])
    db.flush()
    category.user_id = user.id
    method = PaymentMethod(user_id=user.id, name="现金")
    db.add(method)
    db.flush()
    target = datetime(2026, 7, 15).date()
    db.add(
        Transaction(
            user_id=user.id,
            occurred_at=datetime(2026, 7, 15, 9, tzinfo=UTC),
            direction="income",
            amount_cents=100,
            category_id=category.id,
            payment_method_id=method.id,
        )
    )
    row, created = generate_snapshot(db, user.id, target)
    db.commit()
    assert created is True
    assert row.income_cents == 100

    # A normal idempotent run returns the locked snapshot unchanged.
    db.add(
        Transaction(
            user_id=user.id,
            occurred_at=datetime(2026, 7, 15, 10, tzinfo=UTC),
            direction="income",
            amount_cents=250,
            category_id=category.id,
            payment_method_id=method.id,
        )
    )
    db.commit()
    same, was_created = generate_snapshot(db, user.id, target)
    db.commit()
    assert was_created is False
    assert same.id == row.id
    assert same.income_cents == 100

    # Explicit recalculation is the sole path allowed to refresh it.
    refreshed, was_created = generate_snapshot(db, user.id, target, idempotent=False)
    db.commit()
    assert was_created is False
    assert refreshed.id == row.id
    assert refreshed.income_cents == 350
    assert refreshed.is_recalculated is True
    assert refreshed.recalculated_at is not None


def test_generate_snapshot_is_idempotent_and_job_is_all_user_scoped(monkeypatch):
    db = _db()
    first = User(username="first", password_hash="hash")
    second = User(username="second", password_hash="hash")
    db.add_all([first, second])
    db.commit()

    target = datetime(2026, 7, 31).date()
    row, created = generate_snapshot(db, first.id, target)
    db.commit()
    row_id = row.id
    again, created_again = generate_snapshot(db, first.id, target)
    db.commit()
    assert created is True
    assert created_again is False
    assert again.id == row_id
    assert db.query(DailySnapshot).count() == 1

    import app.settlement_job as settlement_job

    monkeypatch.setattr(
        settlement_job,
        "SessionLocal",
        sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False),
    )
    result = run_all_users(target)
    assert result["users"] == 2
    assert result["created"] == 1
    assert result["existing"] == 1
    assert result["failed"] == 0
    assert db.query(DailySnapshot).count() == 2


def test_snapshot_preserves_legacy_direct_opening_balance_before_ledger_row():
    db = _db()
    user = User(username="legacy-opening", password_hash="hash")
    partner = Partner(
        user_id=1,
        type="customer",
        name="Legacy customer",
        prepaid_balance_cents=500,
        credit_limit_cents=1000,
        credit_used_cents=100,
    )
    db.add(user)
    db.flush()
    partner.user_id = user.id
    db.add(partner)
    db.flush()
    # A legacy row may have been initialized directly before the first
    # auditable movement was introduced.
    entry = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=25,
        occurred_at=datetime(2026, 7, 10, tzinfo=UTC),
    )
    db.commit()
    values = _calculate_snapshot(db, user.id, datetime(2026, 7, 9).date())
    account = values["account_balances"][0]
    assert account["prepaid_balance_cents"] == 500
    assert account["credit_limit_cents"] == 1000
    assert account["credit_used_cents"] == 100
    assert account["unsettled_balance_cents"] == 100
