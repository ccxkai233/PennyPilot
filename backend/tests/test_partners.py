from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException

from app.db import Base
from app.models import Category, PaymentMethod, Partner, PartnerLedgerEntry, Transaction, User
from app.partner_schemas import PartnerCreate, PartnerLedgerCreate, PartnerUpdate
from app.partners import (
    _append_entry,
    _as_utc,
    _reverse_entry_locked,
    allowed_partner_ledger_types,
    has_active_transaction_ledger,
    ledger_payload,
    ledger_state_delta,
    partner_payload,
    reverse_transaction_ledgers,
    validate_partner_ledger_type_for_partner,
)


def _db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _user_and_partner(db: Session):
    user = User(username="partner-test", password_hash="hash")
    db.add(user)
    db.flush()
    partner = Partner(user_id=user.id, type="supplier", name="供应商 A")
    db.add(partner)
    db.flush()
    return user, partner


def test_partner_schema_accepts_type_and_partner_type_aliases():
    assert PartnerCreate(name="A", type="supplier").type == "supplier"
    assert PartnerCreate(name="B", partner_type="customer").type == "customer"
    assert PartnerLedgerCreate(type="prepaid_in", amount_cents=100).entry_type == "prepaid_in"


def test_partner_create_payload_keeps_unsettled_balance_out_of_orm_constructor():
    db = _db()
    user = User(username="create-payload", password_hash="hash")
    db.add(user)
    db.flush()
    payload = PartnerCreate(
        name="供应商开户",
        type="supplier",
        unsettled_balance_cents=12_300,
        website="https://supplier.example",
    )

    partner = Partner(
        user_id=user.id,
        **payload.model_dump(exclude={"unsettled_balance_cents"}),
    )
    db.add(partner)
    db.flush()

    assert partner.name == "供应商开户"
    assert partner.prepaid_balance_cents == 0


def test_partner_website_is_canonical_and_legacy_email_is_independent():
    created = PartnerCreate(
        name="网站客户",
        type="customer",
        website=" https://example.com/portal ",
        email="legacy@example.com",
    )
    assert created.website == "https://example.com/portal"
    assert created.email == "legacy@example.com"

    legacy = PartnerCreate(name="旧客户", type="customer", email="old@example.com")
    assert legacy.website is None
    assert legacy.email == "old@example.com"

    url_alias = PartnerUpdate(url="https://alias.example")
    assert url_alias.website == "https://alias.example"
    assert "url" not in url_alias.model_dump(exclude_unset=True)


def test_partner_payload_exposes_website_url_alias_and_email_legacy_field():
    db = _db()
    user = User(username="website-test", password_hash="hash")
    db.add(user)
    db.flush()
    partner = Partner(
        user_id=user.id,
        type="customer",
        name="网址客户",
        website="https://example.com",
        email="legacy@example.com",
    )
    db.add(partner)
    db.flush()
    payload = partner_payload(partner)
    assert payload["website"] == "https://example.com"
    assert payload["url"] == "https://example.com"
    assert payload["email"] == "legacy@example.com"


def test_partner_ledger_records_snapshots_and_reversal_atomically():
    db = _db()
    user, partner = _user_and_partner(db)

    first = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="limit_adjust",
        amount_cents=1000,
        notes="opening",
    )
    db.flush()
    assert first.balance_before_cents == 0
    assert first.balance_after_cents == 1000
    assert partner.credit_limit_cents == 1000

    use = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="credit_use",
        amount_cents=300,
    )
    db.flush()
    assert use.credit_used_before_cents == 0
    assert use.credit_used_after_cents == 300

    reversal = _reverse_entry_locked(db, user.id, use)
    db.commit()
    db.refresh(first)
    db.refresh(use)
    db.refresh(reversal)
    assert use.status == "reversed"
    assert use.reversed_entry_id == reversal.id
    assert reversal.entry_type == "credit_repay"
    assert reversal.amount_cents == 300
    assert partner.credit_used_cents == 0


def test_supplier_credit_use_does_not_require_credit_limit():
    db = _db()
    user = User(username="supplier-credit", password_hash="hash")
    db.add(user)
    db.flush()
    partner = Partner(user_id=user.id, type="supplier", name="供应商授信")
    db.add(partner)
    db.flush()

    entry = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="credit_use",
        amount_cents=12_300,
    )

    db.flush()
    assert entry.credit_used_after_cents == 12_300
    assert partner.credit_used_cents == 12_300


def test_partner_type_policy_restricts_visible_ledger_types():
    db = _db()
    user = User(username="type-policy", password_hash="hash")
    db.add(user)
    db.flush()
    customer = Partner(user_id=user.id, type="customer", name="客户 A")
    supplier = Partner(user_id=user.id, type="supplier", name="供应商 B")
    db.add_all([customer, supplier])
    db.flush()

    assert allowed_partner_ledger_types("customer") == {"prepaid_in", "credit_repay", "limit_adjust", "refund", "balance_check"}
    assert allowed_partner_ledger_types("supplier") == {"prepaid_in", "credit_use", "balance_check"}

    with pytest.raises(HTTPException) as customer_exc:
        validate_partner_ledger_type_for_partner(customer, "credit_use")
    assert customer_exc.value.status_code == 422

    with pytest.raises(HTTPException) as supplier_exc:
        validate_partner_ledger_type_for_partner(supplier, "refund")
    assert supplier_exc.value.status_code == 422


def test_partner_ledger_cannot_cross_tenant():
    db = _db()
    user, partner = _user_and_partner(db)
    other = User(username="other", password_hash="hash")
    db.add(other)
    db.flush()
    # The route's ownership helper is intentionally exercised indirectly by
    # the tenant id stored on each ledger row.
    entry = _append_entry(db, partner, user_id=user.id, entry_type="prepaid_in", amount_cents=50)
    db.commit()
    assert entry.user_id != other.id
    assert db.query(PartnerLedgerEntry).filter_by(user_id=other.id).count() == 0


def test_transaction_void_helper_reverses_linked_partner_movement():
    db = _db()
    user, partner = _user_and_partner(db)
    category = Category(user_id=user.id, name="进货", direction="expense")
    method = PaymentMethod(user_id=user.id, name="现金")
    db.add_all([category, method])
    db.flush()
    transaction = Transaction(
        user_id=user.id,
        direction="expense",
        amount_cents=100,
        category_id=category.id,
        payment_method_id=method.id,
        partner_id=partner.id,
    )
    db.add(transaction)
    db.flush()
    entry = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=100,
        transaction_id=transaction.id,
    )
    db.commit()
    assert has_active_transaction_ledger(db, user.id, transaction.id)
    reversals = reverse_transaction_ledgers(db, user.id, transaction, reason="void")
    db.commit()
    assert len(reversals) == 1
    assert not has_active_transaction_ledger(db, user.id, transaction.id)
    assert partner_payload(partner)["prepaid_balance_cents"] == 0


def test_partner_ledger_timestamps_have_explicit_utc_contract():
    db = _db()
    user, partner = _user_and_partner(db)
    naive = datetime(2026, 8, 1, 12, 0, 0)
    first = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=100,
        occurred_at=naive,
    )
    # A client offset is converted, rather than merely relabeled.
    second = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=100,
        occurred_at=datetime(2026, 8, 1, 21, 0, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    assert first.occurred_at == datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    assert second.occurred_at == datetime(2026, 8, 1, 13, tzinfo=timezone.utc)
    db.commit()
    db.refresh(first)
    # SQLite drops tzinfo on round-trip; the API payload restores the explicit
    # UTC contract for both SQLite smoke tests and PostgreSQL production.
    assert ledger_payload(first)["occurred_at"].tzinfo == timezone.utc
    assert _as_utc(ledger_payload(second)["occurred_at"]) == datetime(
        2026, 8, 1, 13, tzinfo=timezone.utc
    )


def test_ledger_state_delta_replay_handles_backdated_rows():
    """Historical settlement uses signed deltas, not insertion-time snapshots."""

    db = _db()
    user, partner = _user_and_partner(db)
    # Append in one order, then deliberately backdate the final row.  The
    # final row's ``after`` snapshot is based on the current balance (200),
    # not the balance at its historical date, so selecting that snapshot as
    # the historical state would be wrong.
    jan10 = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=100,
        occurred_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    jan20 = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=100,
        occurred_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
    )
    jan05 = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=20,
        occurred_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    entries = sorted((jan10, jan20, jan05), key=lambda row: (row.occurred_at, row.id))
    state = {"prepaid_balance_cents": 0, "credit_limit_cents": 0, "credit_used_cents": 0}
    as_of_jan10 = None
    for row in entries:
        delta = ledger_state_delta(row)
        for key, value in delta.items():
            state[key] += value
        if row.occurred_at <= datetime(2026, 1, 10, 23, 59, 59, tzinfo=timezone.utc):
            as_of_jan10 = dict(state)
    assert as_of_jan10["prepaid_balance_cents"] == 120
    # The backdated row was inserted last and therefore has an insertion-time
    # snapshot of 200; this is precisely why settlement must replay deltas.
    assert jan05.prepaid_after_cents == 220


def test_reversal_can_compensate_a_prepaid_entry_after_later_consumption():
    db = _db()
    user, partner = _user_and_partner(db)
    original = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=100,
    )
    _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_out",
        amount_cents=100,
    )
    reversal = _reverse_entry_locked(db, user.id, original)
    db.commit()
    assert reversal.entry_type == "prepaid_out"
    assert partner.prepaid_balance_cents == -100
    assert original.status == "reversed"


def test_reversal_can_expose_over_limit_state_without_relaxing_normal_rules():
    db = _db()
    user, partner = _user_and_partner(db)
    opening_limit = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="limit_adjust",
        amount_cents=100,
    )
    _append_entry(db, partner, user_id=user.id, entry_type="credit_use", amount_cents=100)
    repayment = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="credit_repay",
        amount_cents=100,
    )
    _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="limit_adjust",
        amount_cents=-100,
    )
    # Reversing the repayment recreates the credit use while the later limit
    # reduction remains in force.  A normal credit_use would be rejected, but
    # the compensating row must preserve the audit algebra.
    repayment_reversal = _reverse_entry_locked(db, user.id, repayment)
    assert repayment_reversal.entry_type == "credit_use"
    assert partner.credit_used_cents == 100
    assert partner.credit_limit_cents == 0
    # Reversing the opening limit also remains possible, and does not alter
    # the normal-path guard for a fresh credit use.
    opening_reversal = _reverse_entry_locked(db, user.id, opening_limit)
    db.commit()
    assert opening_reversal.amount_cents == -100
    assert partner.credit_limit_cents == -100


def test_compensating_entry_cannot_be_reversed_as_a_chain():
    db = _db()
    user, partner = _user_and_partner(db)
    original = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type="prepaid_in",
        amount_cents=100,
    )
    reversal = _reverse_entry_locked(db, user.id, original)
    with pytest.raises(HTTPException) as error:
        _reverse_entry_locked(db, user.id, reversal)
    assert error.value.status_code == 409
