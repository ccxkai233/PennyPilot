"""Supplier/customer current-account API.

The module deliberately keeps partner balance mutations in one small set of
helpers.  Every mutation locks the partner row, snapshots all three balance
dimensions, writes a ledger row, and commits together.  Ledger rows are never
deleted; a correction is represented by a compensating row.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import Partner, PartnerLedgerEntry, Transaction, User
from .partner_schemas import (
    PartnerCreate,
    PartnerLedgerCreate,
    PartnerLedgerListResponse,
    PartnerLedgerRead,
    PartnerLedgerReverseRequest,
    PartnerListResponse,
    PartnerRead,
    PartnerUpdate,
)
from .timezone import to_utc, utc_bounds_for_business_date


router = APIRouter(prefix="/api", tags=["partners"])

LEDGER_TYPES = {
    "prepaid_in",
    "prepaid_out",
    "credit_use",
    "credit_repay",
    "limit_adjust",
    "refund",
    # A balance check records an externally observed balance without changing
    # any of the three account dimensions. It is intentionally zero-valued.
    "balance_check",
}
PARTNER_LEDGER_TYPES_BY_TYPE = {
    "customer": {
        "prepaid_in",
        "credit_repay",
        "limit_adjust",
        "refund",
        "balance_check",
    },
    "supplier": {
        "prepaid_in",
        "credit_use",
        "balance_check",
    },
}
INVERSE_LEDGER_TYPES = {
    "prepaid_in": "prepaid_out",
    "prepaid_out": "prepaid_in",
    "credit_use": "credit_repay",
    "credit_repay": "credit_use",
    "limit_adjust": "limit_adjust",
    # A refund reduces the prepaid balance; its compensating movement adds it
    # back.  This keeps both operations auditable without mutating history.
    "refund": "prepaid_in",
    "balance_check": "balance_check",
}


def _user(request: Request, db: Session) -> User:
    return current_user(request, db)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime:
    """Normalize API/internal timestamps to an aware UTC datetime.

    PostgreSQL's ``timestamptz`` accepts a naive value by applying the
    connection's session timezone, while SQLite drops timezone information
    altogether.  Letting either behavior leak into the ledger makes a date
    filter (and, consequently, a daily settlement) depend on the deployment
    timezone.  Treat a naive client value as UTC for backwards compatibility
    and convert aware values explicitly.
    """

    return to_utc(value)


def _commit(db: Session, duplicate_message: str = "Record already exists") -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, duplicate_message) from exc


def _owned_partner(
    db: Session, user_id: int, partner_id: int, *, lock: bool = False
) -> Partner:
    statement = select(Partner).where(Partner.id == partner_id, Partner.user_id == user_id)
    if lock:
        statement = statement.with_for_update()
    partner = db.scalar(statement)
    if partner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner not found")
    return partner


def _owned_transaction(
    db: Session, user_id: int, transaction_id: int, *, lock: bool = False
) -> Transaction:
    statement = select(Transaction).where(
        Transaction.id == transaction_id,
        Transaction.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    transaction = db.scalar(statement)
    if transaction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return transaction


def partner_payload(partner: Partner) -> dict:
    """Return a response-safe partner dict including derived unsettled balance."""

    website = partner.website
    unsettled_balance_cents = int(partner.credit_used_cents or 0) if str(partner.type).lower() == "customer" else int(partner.prepaid_balance_cents or 0)
    return {
        "id": partner.id,
        "user_id": partner.user_id,
        "type": partner.type,
        "name": partner.name,
        "contact": partner.contact,
        "phone": partner.phone,
        "website": website,
        # ``url`` is a read-compatible alias for clients that use the shorter
        # field name. Keep the legacy email value independent and untouched.
        "url": website,
        "email": partner.email,
        "unsettled_balance_cents": unsettled_balance_cents,
        "prepaid_balance_cents": partner.prepaid_balance_cents,
        "credit_limit_cents": partner.credit_limit_cents,
        "credit_used_cents": partner.credit_used_cents,
        # Preserve a negative remainder as an explicit over-limit risk signal
        # (historical reversals may temporarily expose one).  Clamping here
        # would make the current-account page disagree with daily snapshots.
        "credit_remaining_cents": partner.credit_limit_cents - partner.credit_used_cents,
        "status": partner.status,
        "notes": partner.notes,
        "created_at": partner.created_at,
        "updated_at": partner.updated_at,
    }


def ledger_payload(entry: PartnerLedgerEntry) -> dict:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "partner_id": entry.partner_id,
        # SQLite (used by local/smoke databases) strips tzinfo from
        # ``DateTime(timezone=True)`` values.  Return the same explicit UTC
        # contract as PostgreSQL so clients can safely use the timestamp in
        # date-boundary calculations.
        "occurred_at": _as_utc(entry.occurred_at),
        "entry_type": entry.entry_type,
        "amount_cents": entry.amount_cents,
        "balance_before_cents": entry.balance_before_cents,
        "balance_after_cents": entry.balance_after_cents,
        "prepaid_before_cents": entry.prepaid_before_cents,
        "prepaid_after_cents": entry.prepaid_after_cents,
        "credit_limit_before_cents": entry.credit_limit_before_cents,
        "credit_limit_after_cents": entry.credit_limit_after_cents,
        "credit_used_before_cents": entry.credit_used_before_cents,
        "credit_used_after_cents": entry.credit_used_after_cents,
        "transaction_id": entry.transaction_id,
        "reversal_of_id": entry.reversal_of_id,
        "reversed_entry_id": entry.reversed_entry_id,
        "status": entry.status,
        "notes": entry.notes,
        "created_at": entry.created_at,
    }


def ledger_state_delta(entry: PartnerLedgerEntry) -> dict[str, int]:
    """Return the signed state change represented by one ledger row.

    Daily snapshots must replay these deltas in ``(occurred_at, id)`` order,
    rather than selecting a row's ``*_after`` values as the historical state.
    A user may append a backdated row; its snapshots describe the balance at
    insertion time, while the before/after *difference* remains the durable
    signed movement.  Keeping this tiny helper beside the mutation code gives
    settlement/reporting code one canonical interpretation for all six entry
    types, including compensating reversals.
    """

    return {
        "prepaid_balance_cents": int(entry.prepaid_after_cents)
        - int(entry.prepaid_before_cents),
        "credit_limit_cents": int(entry.credit_limit_after_cents)
        - int(entry.credit_limit_before_cents),
        "credit_used_cents": int(entry.credit_used_after_cents)
        - int(entry.credit_used_before_cents),
    }


def _ensure_active_partner(partner: Partner) -> None:
    if partner.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Inactive partners cannot receive ledger entries")


def allowed_partner_ledger_types(partner_type: str | None) -> set[str]:
    return set(PARTNER_LEDGER_TYPES_BY_TYPE.get(str(partner_type or "").lower(), LEDGER_TYPES))


def validate_partner_ledger_type_for_partner(partner: Partner, entry_type: str) -> None:
    allowed = allowed_partner_ledger_types(partner.type)
    if entry_type in allowed:
        return
    if str(partner.type).lower() == "customer":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Customer accounts only support prepaid recharge, credit repayment, credit-limit adjustments, refunds, and balance checks",
        )
    if str(partner.type).lower() == "supplier":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Supplier accounts only support prepaid recharge, credit payment, and balance checks",
        )
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid partner ledger type for this account")


def _apply_movement(
    partner: Partner,
    entry_type: str,
    amount_cents: int,
    *,
    enforce_constraints: bool = True,
) -> tuple[int, int, dict[str, int]]:
    """Apply one movement and return (generic before, generic after, snapshot).

    The caller must have locked ``partner``.  Raising before constructing a
    ledger row means the surrounding request transaction is left untouched.
    """

    if entry_type not in LEDGER_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid partner ledger type")
    if (amount_cents == 0 and entry_type != "balance_check") or (entry_type not in {"limit_adjust", "balance_check"} and amount_cents < 0):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid ledger amount")

    prepaid_before = int(partner.prepaid_balance_cents or 0)
    limit_before = int(partner.credit_limit_cents or 0)
    used_before = int(partner.credit_used_cents or 0)
    prepaid_after = prepaid_before
    limit_after = limit_before
    used_after = used_before

    if entry_type == "prepaid_in":
        prepaid_after += amount_cents
        balance_before, balance_after = prepaid_before, prepaid_after
    elif entry_type in {"prepaid_out", "refund"}:
        prepaid_after -= amount_cents
        if enforce_constraints and prepaid_after < 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Prepaid balance cannot be negative")
        balance_before, balance_after = prepaid_before, prepaid_after
    elif entry_type == "credit_use":
        used_after += amount_cents
        if enforce_constraints and str(partner.type).lower() == "customer" and used_after > limit_before:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Credit use cannot exceed the credit limit",
            )
        balance_before, balance_after = used_before, used_after
    elif entry_type == "credit_repay":
        used_after -= amount_cents
        if enforce_constraints and used_after < 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Credit used balance cannot be negative")
        balance_before, balance_after = used_before, used_after
    elif entry_type == "balance_check":
        # No state changes; the before/after snapshots still make the
        # observation auditable and allow settlement replay to treat it as a
        # zero delta.
        balance_before = prepaid_before
        balance_after = prepaid_before
    else:  # limit_adjust
        limit_after += amount_cents
        if enforce_constraints and (limit_after < 0 or limit_after < used_before):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Credit limit cannot be below credit used balance",
            )
        balance_before, balance_after = limit_before, limit_after

    partner.prepaid_balance_cents = prepaid_after
    partner.credit_limit_cents = limit_after
    partner.credit_used_cents = used_after
    return balance_before, balance_after, {
        "prepaid_before_cents": prepaid_before,
        "prepaid_after_cents": prepaid_after,
        "credit_limit_before_cents": limit_before,
        "credit_limit_after_cents": limit_after,
        "credit_used_before_cents": used_before,
        "credit_used_after_cents": used_after,
    }


def _append_entry(
    db: Session,
    partner: Partner,
    *,
    user_id: int,
    entry_type: str,
    amount_cents: int,
    occurred_at: datetime | None = None,
    transaction_id: int | None = None,
    reversal_of_id: int | None = None,
    notes: str | None = None,
    allow_inactive: bool = False,
    allow_constraint_breach: bool = False,
) -> PartnerLedgerEntry:
    if partner.user_id != user_id:
        # Defensive invariant for helper callers. Public routes resolve the
        # partner through ``_owned_partner``; this prevents a future internal
        # path from writing a cross-tenant ledger row if that boundary is
        # accidentally bypassed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner not found")
    if not allow_inactive:
        _ensure_active_partner(partner)
    before, after, snapshot = _apply_movement(
        partner,
        entry_type,
        amount_cents,
        enforce_constraints=not allow_constraint_breach,
    )
    entry = PartnerLedgerEntry(
        user_id=user_id,
        partner_id=partner.id,
        occurred_at=_as_utc(occurred_at),
        entry_type=entry_type,
        amount_cents=amount_cents,
        balance_before_cents=before,
        balance_after_cents=after,
        **snapshot,
        transaction_id=transaction_id,
        reversal_of_id=reversal_of_id,
        notes=notes,
    )
    db.add(entry)
    return entry


def _link_transaction(
    db: Session,
    user_id: int,
    partner: Partner,
    transaction_id: int,
    *,
    transaction: Transaction | None = None,
) -> Transaction:
    """Validate and associate a transaction with ``partner``.

    Callers that mutate both rows should acquire the transaction lock before
    the partner lock (the same order used by the accounting void path) and
    pass the already-locked instance here. When omitted, this helper obtains
    the row lock itself for backwards-compatible internal callers.
    """

    # Lock the transaction while checking/setting its partner association. A
    # concurrent ledger request must not pass the duplicate check and create
    # two active movements for the same transaction.
    if transaction is None:
        transaction = _owned_transaction(db, user_id, transaction_id, lock=True)
    elif transaction.id != transaction_id or transaction.user_id != user_id:
        # Do not trust an instance supplied by an internal caller across tenant
        # boundaries. Re-read through the ownership helper for a uniform
        # not-found response rather than leaking another tenant's row.
        transaction = _owned_transaction(db, user_id, transaction_id, lock=True)
    if transaction.status == "voided":
        raise HTTPException(status.HTTP_409_CONFLICT, "Voided transactions cannot be linked")
    if transaction.partner_id is not None and transaction.partner_id != partner.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Transaction belongs to another partner")
    existing = db.scalar(
        select(PartnerLedgerEntry).where(
            PartnerLedgerEntry.user_id == user_id,
            PartnerLedgerEntry.transaction_id == transaction_id,
            PartnerLedgerEntry.reversal_of_id.is_(None),
            PartnerLedgerEntry.status == "normal",
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Transaction already has a partner ledger entry")
    transaction.partner_id = partner.id
    return transaction


def _reverse_entry_locked(
    db: Session,
    user_id: int,
    entry: PartnerLedgerEntry,
    *,
    reason: str | None = None,
) -> PartnerLedgerEntry:
    """Create a compensating entry for an already locked normal entry."""

    if entry.user_id != user_id:
        # Public routes already scope the lookup, but this helper is also used
        # by transaction voiding and tests.  Keep the tenant boundary inside
        # the mutation primitive so an accidentally supplied ORM instance can
        # never be used to write a cross-user reversal.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ledger entry not found")
    if entry.reversal_of_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Compensating ledger entries cannot be reversed again",
        )
    # SQLAlchemy column defaults are populated on flush; internal callers may
    # reverse a freshly appended row before that flush, in which case
    # ``status`` is still ``None`` even though the durable default is normal.
    if entry.status not in (None, "normal") or entry.reversed_entry_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ledger entry is not reversible")
    partner = _owned_partner(db, user_id, entry.partner_id, lock=True)
    inverse_type = INVERSE_LEDGER_TYPES[entry.entry_type]
    inverse_amount = -entry.amount_cents if entry.entry_type == "limit_adjust" else entry.amount_cents
    note = reason or f"冲销流水 #{entry.id}"
    reversal = _append_entry(
        db,
        partner,
        user_id=user_id,
        entry_type=inverse_type,
        amount_cents=inverse_amount,
        occurred_at=_now(),
        transaction_id=entry.transaction_id,
        reversal_of_id=entry.id,
        notes=note,
        allow_inactive=True,
        # A compensating entry must be writable even when later movements have
        # consumed/repaid the original amount.  In that case faithfully
        # undoing history can temporarily expose a negative prepaid balance,
        # over-limit credit, or negative used credit; these states are visible
        # risk signals and normal (non-reversal) entries still enforce all
        # invariants.
        allow_constraint_breach=True,
    )
    db.flush()
    entry.status = "reversed"
    entry.reversed_entry_id = reversal.id
    return reversal


def reverse_transaction_ledgers(
    db: Session, user_id: int, transaction: Transaction, *, reason: str | None = None
) -> list[PartnerLedgerEntry]:
    """Reverse all active partner movements linked to ``transaction``.

    This helper intentionally does not commit.  ``accounting.void_transaction``
    calls it before its own commit so the transaction status, payment-method
    balance, and partner balance are one atomic database operation.
    """

    entries = db.scalars(
        select(PartnerLedgerEntry)
        .where(
            PartnerLedgerEntry.user_id == user_id,
            PartnerLedgerEntry.transaction_id == transaction.id,
            PartnerLedgerEntry.reversal_of_id.is_(None),
            PartnerLedgerEntry.status == "normal",
        )
        .order_by(PartnerLedgerEntry.id)
        .with_for_update()
    ).all()
    reversals: list[PartnerLedgerEntry] = []
    for entry in entries:
        reversals.append(
            _reverse_entry_locked(
                db,
                user_id,
                entry,
                reason=reason or f"作废交易 #{transaction.id}，自动冲销",
            )
        )
    return reversals


def has_active_transaction_ledger(db: Session, user_id: int, transaction_id: int) -> bool:
    return (
        db.scalar(
            select(func.count(PartnerLedgerEntry.id)).where(
                PartnerLedgerEntry.user_id == user_id,
                PartnerLedgerEntry.transaction_id == transaction_id,
                PartnerLedgerEntry.reversal_of_id.is_(None),
                PartnerLedgerEntry.status == "normal",
            )
        )
        or 0
    ) > 0


def validate_partner_reference(db: Session, user_id: int, partner_id: int | None) -> Partner | None:
    """Validate a transaction's optional partner reference for core API use."""

    if partner_id is None:
        return None
    partner = _owned_partner(db, user_id, partner_id)
    if partner.status != "active":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Partner is inactive")
    return partner


def resolve_partner_reference(
    db: Session,
    user_id: int,
    partner_id: int | None = None,
    partner_name: str | None = None,
) -> Partner | None:
    """Resolve a partner by ID first, then by a unique active name match."""

    partner = validate_partner_reference(db, user_id, partner_id)
    if partner is not None or not partner_name:
        return partner
    needle = str(partner_name).strip().lower()
    if not needle:
        return None
    partners = db.scalars(
        select(Partner).where(Partner.user_id == user_id, Partner.status == "active")
    ).all()
    exact = [item for item in partners if item.name.strip().lower() == needle]
    if len(exact) == 1:
        return exact[0]
    partial = [
        item
        for item in partners
        if needle in item.name.strip().lower() or item.name.strip().lower() in needle
    ]
    if len(partial) == 1:
        return partial[0]
    if len(exact) > 1 or len(partial) > 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Partner name is ambiguous")
    return None


@router.get("/partners", response_model=PartnerListResponse)
def list_partners(
    request: Request,
    partner_type: str | None = Query(default=None, alias="type", pattern="^(supplier|customer)$"),
    partner_status: str | None = Query(default=None, alias="status", pattern="^(active|inactive)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    filters = [Partner.user_id == user.id]
    if partner_type is not None:
        filters.append(Partner.type == partner_type)
    if partner_status is not None:
        filters.append(Partner.status == partner_status)
    total = db.scalar(select(func.count(Partner.id)).where(*filters)) or 0
    items = db.scalars(
        select(Partner)
        .where(*filters)
        .order_by(Partner.status, Partner.type, Partner.name, Partner.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PartnerListResponse(
        items=[partner_payload(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/partners", response_model=PartnerRead, status_code=status.HTTP_201_CREATED)
def create_partner(payload: PartnerCreate, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    # ``unsettled_balance_cents`` is a derived/API convenience field.  It is
    # represented by the auditable opening ledger entry below, not by a
    # column on the Partner ORM model.
    partner_data = payload.model_dump(exclude={"unsettled_balance_cents"})
    partner = Partner(user_id=user.id, **partner_data)
    # Opening balances are represented as normal ledger rows, not hidden
    # mutations, so the account is auditable from its first day.
    opening_unsettled = payload.unsettled_balance_cents
    use_unsettled = bool(opening_unsettled)
    if not use_unsettled:
        opening_unsettled = payload.credit_used_cents if str(payload.type).lower() == "customer" else payload.prepaid_balance_cents
    opening_prepaid = 0 if use_unsettled else payload.prepaid_balance_cents
    opening_limit = payload.credit_limit_cents
    opening_used = 0 if use_unsettled else payload.credit_used_cents
    partner.prepaid_balance_cents = 0
    partner.credit_limit_cents = 0
    partner.credit_used_cents = 0
    db.add(partner)
    try:
        db.flush()
        if opening_unsettled:
            _append_entry(
                db,
                partner,
                user_id=user.id,
                entry_type="credit_use" if str(payload.type).lower() == "customer" else "prepaid_in",
                amount_cents=opening_unsettled,
                notes="开户初始未结算余额",
                allow_inactive=True,
            )
        if opening_prepaid and str(payload.type).lower() != "customer":
            _append_entry(
                db,
                partner,
                user_id=user.id,
                entry_type="prepaid_in",
                amount_cents=opening_prepaid,
                notes="开户初始预存余额",
                allow_inactive=True,
            )
        if opening_limit:
            _append_entry(
                db,
                partner,
                user_id=user.id,
                entry_type="limit_adjust",
                amount_cents=opening_limit,
                notes="开户初始授信额度",
                allow_inactive=True,
            )
        if opening_used and str(payload.type).lower() == "customer":
            _append_entry(
                db,
                partner,
                user_id=user.id,
                entry_type="credit_use",
                amount_cents=opening_used,
                notes="开户初始授信已用",
                allow_inactive=True,
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A partner with this type and name already exists") from exc
    db.refresh(partner)
    return partner_payload(partner)


@router.get("/partners/{partner_id}/ledger", response_model=PartnerLedgerListResponse)
def list_partner_ledger(
    partner_id: int,
    request: Request,
    entry_type: str | None = Query(default=None, alias="type", pattern="^(prepaid_in|prepaid_out|credit_use|credit_repay|limit_adjust|refund|balance_check)$"),
    ledger_status: str | None = Query(default=None, alias="status", pattern="^(normal|reversed)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    _owned_partner(db, user.id, partner_id)
    filters = [PartnerLedgerEntry.user_id == user.id, PartnerLedgerEntry.partner_id == partner_id]
    if entry_type is not None:
        filters.append(PartnerLedgerEntry.entry_type == entry_type)
    if ledger_status is not None:
        filters.append(PartnerLedgerEntry.status == ledger_status)
    if start_date is not None:
        start_boundary, _ = utc_bounds_for_business_date(start_date)
        filters.append(PartnerLedgerEntry.occurred_at >= start_boundary)
    if end_date is not None:
        _, end_boundary = utc_bounds_for_business_date(end_date)
        filters.append(PartnerLedgerEntry.occurred_at < end_boundary)
    total = db.scalar(select(func.count(PartnerLedgerEntry.id)).where(*filters)) or 0
    rows = db.scalars(
        select(PartnerLedgerEntry)
        .where(*filters)
        .order_by(PartnerLedgerEntry.occurred_at.desc(), PartnerLedgerEntry.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PartnerLedgerListResponse(
        items=[ledger_payload(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/partners/{partner_id}/balance", response_model=PartnerRead)
def get_partner_balance(partner_id: int, request: Request, db: Session = Depends(get_db)):
    """Return the current auditable balance snapshot for a partner.

    The regular partner resource already contains these fields; this explicit
    endpoint keeps mobile clients from having to know that implementation
    detail and matches the balance-focused UI/API contract.
    """

    user = _user(request, db)
    return partner_payload(_owned_partner(db, user.id, partner_id))


@router.get("/partners/{partner_id}", response_model=PartnerRead)
def get_partner(partner_id: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    return partner_payload(_owned_partner(db, user.id, partner_id))


@router.patch("/partners/{partner_id}", response_model=PartnerRead)
def update_partner(
    partner_id: int,
    payload: PartnerUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    partner = _owned_partner(db, user.id, partner_id, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(partner, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A partner with this type and name already exists") from exc
    db.refresh(partner)
    return partner_payload(partner)


@router.delete("/partners/{partner_id}", response_model=PartnerRead)
def deactivate_partner(partner_id: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    partner = _owned_partner(db, user.id, partner_id, lock=True)
    partner.status = "inactive"
    db.commit()
    db.refresh(partner)
    return partner_payload(partner)


@router.post(
    "/partners/{partner_id}/ledger",
    response_model=PartnerLedgerRead,
    status_code=status.HTTP_201_CREATED,
)
def create_partner_ledger(
    partner_id: int,
    payload: PartnerLedgerCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    transaction = None
    if payload.transaction_id is not None:
        # Keep lock ordering consistent with ``void_transaction``: transaction
        # first, partner second.  This avoids a PostgreSQL deadlock when a
        # ledger association races with voiding the same transaction.
        transaction = _owned_transaction(db, user.id, payload.transaction_id, lock=True)
    partner = _owned_partner(db, user.id, partner_id, lock=True)
    if transaction is not None:
        transaction = _link_transaction(
            db,
            user.id,
            partner,
            payload.transaction_id,
            transaction=transaction,
        )
    validate_partner_ledger_type_for_partner(partner, payload.entry_type)
    entry = _append_entry(
        db,
        partner,
        user_id=user.id,
        entry_type=payload.entry_type,
        amount_cents=payload.amount_cents,
        occurred_at=payload.occurred_at,
        transaction_id=transaction.id if transaction else None,
        notes=payload.notes,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Could not save partner ledger entry") from exc
    db.refresh(entry)
    return ledger_payload(entry)


@router.get("/partners/{partner_id}/ledger/{entry_id}", response_model=PartnerLedgerRead)
def get_partner_ledger_entry(
    partner_id: int, entry_id: int, request: Request, db: Session = Depends(get_db)
):
    user = _user(request, db)
    _owned_partner(db, user.id, partner_id)
    entry = db.scalar(
        select(PartnerLedgerEntry).where(
            PartnerLedgerEntry.id == entry_id,
            PartnerLedgerEntry.partner_id == partner_id,
            PartnerLedgerEntry.user_id == user.id,
        )
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner ledger entry not found")
    return ledger_payload(entry)


@router.post(
    "/partners/{partner_id}/ledger/{entry_id}/reverse",
    response_model=PartnerLedgerRead,
)
def reverse_partner_ledger(
    partner_id: int,
    entry_id: int,
    request: Request,
    payload: PartnerLedgerReverseRequest | None = None,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    _owned_partner(db, user.id, partner_id)
    entry = db.scalar(
        select(PartnerLedgerEntry)
        .where(
            PartnerLedgerEntry.id == entry_id,
            PartnerLedgerEntry.partner_id == partner_id,
            PartnerLedgerEntry.user_id == user.id,
        )
        .with_for_update()
    )
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner ledger entry not found")
    reversal = _reverse_entry_locked(
        db,
        user.id,
        entry,
        reason=payload.reason if payload else None,
    )
    db.commit()
    db.refresh(reversal)
    return ledger_payload(reversal)
