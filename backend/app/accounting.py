"""Authenticated CRUD endpoints for the core bookkeeping dictionaries and ledger."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from .auth import current_user
from .db import get_db
from .models import Category, Partner, PaymentMethod, Transaction, User
from .partners import (
    _as_utc,
    has_active_transaction_ledger,
    _owned_partner,
    reverse_transaction_ledgers,
    validate_partner_reference,
)
from .schemas import (
    CategoryCreate,
    CategoryListResponse,
    CategoryRead,
    CategoryUpdate,
    PaymentMethodCreate,
    PaymentMethodListResponse,
    PaymentMethodRead,
    PaymentMethodUpdate,
    TransactionCreate,
    TransactionListResponse,
    TransactionRead,
    TransactionTotalsResponse,
    TransactionUpdate,
    TransactionVoidRequest,
)
from .timezone import utc_bounds_for_business_date


router = APIRouter(prefix="/api", tags=["bookkeeping"])


def _user(request: Request, db: Session) -> User:
    return current_user(request, db)


def _commit(db: Session, duplicate_message: str = "Record already exists") -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, duplicate_message) from exc


def _owned_category(db: Session, user_id: int, category_id: int, *, lock: bool = False) -> Category:
    statement = select(Category).where(Category.id == category_id, Category.user_id == user_id)
    if lock:
        statement = statement.with_for_update()
    category = db.scalar(statement)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category


def _owned_method(db: Session, user_id: int, method_id: int, *, lock: bool = False) -> PaymentMethod:
    statement = select(PaymentMethod).where(
        PaymentMethod.id == method_id,
        PaymentMethod.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    method = db.scalar(statement)
    if method is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment method not found")
    return method


def _transaction_balance_totals(db: Session, user_id: int) -> dict[int, int]:
    """Aggregate effective balances from all normal transactions by account.

    Older/default cash methods intentionally did not maintain
    ``current_balance_cents``. Their complete transaction ledger is still
    authoritative for a zero-opening-balance view, including both sides of an
    internal transfer. Tracked accounts keep using their stored balance so a
    manually supplied opening balance is preserved.
    """

    source_delta = case(
        (Transaction.kind == "transfer", -Transaction.amount_cents),
        (
            PaymentMethod.account_role == "liability",
            case(
                (Transaction.direction == "expense", Transaction.amount_cents),
                else_=-Transaction.amount_cents,
            ),
        ),
        else_=case(
            (Transaction.direction == "income", Transaction.amount_cents),
            else_=-Transaction.amount_cents,
        ),
    )
    source_rows = db.execute(
        select(Transaction.payment_method_id, func.coalesce(func.sum(source_delta), 0))
        .join(PaymentMethod, PaymentMethod.id == Transaction.payment_method_id)
        .where(Transaction.user_id == user_id, Transaction.status == "normal")
        .group_by(Transaction.payment_method_id)
    ).all()
    totals = {int(method_id): int(amount or 0) for method_id, amount in source_rows}

    target = aliased(PaymentMethod)
    target_delta = case(
        (target.account_role == "liability", -Transaction.amount_cents),
        else_=Transaction.amount_cents,
    )
    target_rows = db.execute(
        select(Transaction.transfer_payment_method_id, func.coalesce(func.sum(target_delta), 0))
        .join(target, target.id == Transaction.transfer_payment_method_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.status == "normal",
            Transaction.kind == "transfer",
            Transaction.transfer_payment_method_id.is_not(None),
        )
        .group_by(Transaction.transfer_payment_method_id)
    ).all()
    for method_id, amount in target_rows:
        totals[int(method_id)] = totals.get(int(method_id), 0) + int(amount or 0)
    return totals


def _owned_transaction(db: Session, user_id: int, transaction_id: int, *, lock: bool = False) -> Transaction:
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


def _validate_cashflow_dictionary_pair(category: Category, method: PaymentMethod, direction: str) -> None:
    if not category.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Category is inactive")
    if category.direction != direction:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Category direction does not match transaction direction",
        )
    if not method.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Payment method is inactive")


def _validate_transfer_methods(source: PaymentMethod, target: PaymentMethod) -> None:
    if not source.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Source account is inactive")
    if not target.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Target account is inactive")
    if source.id == target.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transfer requires two different accounts")


def _cashflow_balance_delta(method: PaymentMethod, direction: str, amount_cents: int) -> int:
    """Return balance delta for an ordinary income/expense on one account."""

    if getattr(method, "account_role", "cash") == "liability":
        # A credit-card/loan expense increases the outstanding debt; an income
        # entry on the liability account reduces it.
        return amount_cents if direction == "expense" else -amount_cents
    return amount_cents if direction == "income" else -amount_cents


def _apply_balance(method: PaymentMethod, direction: str, amount_cents: int, *, reverse: bool = False) -> None:
    if not method.track_balance:
        return
    current = method.current_balance_cents or 0
    delta = _cashflow_balance_delta(method, direction, amount_cents)
    method.current_balance_cents = current - delta if reverse else current + delta


def _transfer_target_delta(method: PaymentMethod, amount_cents: int) -> int:
    # Moving money to a liability account is repayment: the debt decreases.
    if getattr(method, "account_role", "cash") == "liability":
        return -amount_cents
    return amount_cents


def _apply_transfer_balance(
    source: PaymentMethod,
    target: PaymentMethod,
    amount_cents: int,
    *,
    reverse: bool = False,
) -> None:
    """Apply an internal transfer between two tracked accounts.

    ``payment_method_id`` is the source account.  A transfer moves value out of
    that account and into ``transfer_payment_method_id``.  If the target is a
    liability account, "into" means paying down debt.
    """

    source_delta = -amount_cents
    target_delta = _transfer_target_delta(target, amount_cents)
    if reverse:
        source_delta = -source_delta
        target_delta = -target_delta
    if source.track_balance:
        source.current_balance_cents = (source.current_balance_cents or 0) + source_delta
    if target.track_balance:
        target.current_balance_cents = (target.current_balance_cents or 0) + target_delta


def _apply_transaction_balance(
    transaction: Transaction,
    method: PaymentMethod,
    transfer_method: PaymentMethod | None = None,
    *,
    reverse: bool = False,
) -> None:
    if transaction.kind == "transfer":
        if transfer_method is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transfer target account is required")
        _apply_transfer_balance(method, transfer_method, transaction.amount_cents, reverse=reverse)
    else:
        _apply_balance(method, transaction.direction, transaction.amount_cents, reverse=reverse)


def _owned_optional_category(db: Session, user_id: int, category_id: int | None) -> Category | None:
    return _owned_category(db, user_id, category_id) if category_id is not None else None


def _owned_method_pair(
    db: Session,
    user_id: int,
    method_id: int,
    transfer_method_id: int | None,
    *,
    lock: bool = False,
) -> tuple[PaymentMethod, PaymentMethod | None]:
    if transfer_method_id is None:
        return _owned_method(db, user_id, method_id, lock=lock), None
    mapping: dict[int, PaymentMethod] = {}
    for item_id in sorted({method_id, transfer_method_id}):
        mapping[item_id] = _owned_method(db, user_id, item_id, lock=lock)
    return mapping[method_id], mapping[transfer_method_id]


def _validate_transaction_dictionaries(
    *,
    kind: str,
    direction: str,
    category: Category | None,
    method: PaymentMethod,
    transfer_method: PaymentMethod | None,
) -> None:
    if kind == "transfer":
        if transfer_method is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Transfer target account is required")
        _validate_transfer_methods(method, transfer_method)
        return
    if category is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Category is required")
    _validate_cashflow_dictionary_pair(category, method, direction)


def _transaction_payload(
    transaction: Transaction,
    category_name: str | None = None,
    method_name: str | None = None,
    transfer_method_name: str | None = None,
    partner_name: str | None = None,
) -> dict:
    return {
        "id": transaction.id,
        "user_id": transaction.user_id,
        # Keep the API's date-boundary contract explicit even when a SQLite
        # smoke database (which drops tzinfo) is used.
        "occurred_at": _as_utc(transaction.occurred_at),
        "kind": transaction.kind,
        "direction": transaction.direction,
        "amount_cents": transaction.amount_cents,
        "category_id": transaction.category_id,
        "payment_method_id": transaction.payment_method_id,
        "transfer_payment_method_id": transaction.transfer_payment_method_id,
        "partner_id": transaction.partner_id,
        "notes": transaction.notes,
        "source": transaction.source,
        "status": transaction.status,
        "voided_at": _as_utc(transaction.voided_at) if transaction.voided_at else None,
        "void_reason": transaction.void_reason,
        "created_at": _as_utc(transaction.created_at),
        "updated_at": _as_utc(transaction.updated_at),
        "category_name": category_name,
        "payment_method_name": method_name,
        "transfer_payment_method_name": transfer_method_name,
        "partner_name": partner_name,
    }


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(
    request: Request,
    direction: str | None = Query(default=None, pattern="^(income|expense)$"),
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    filters = [Category.user_id == user.id]
    if direction is not None:
        filters.append(Category.direction == direction)
    if is_active is not None:
        filters.append(Category.is_active == is_active)
    total = db.scalar(select(func.count(Category.id)).where(*filters)) or 0
    items = db.scalars(
        select(Category)
        .where(*filters)
        .order_by(Category.sort_order, Category.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return CategoryListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    category = Category(user_id=user.id, **payload.model_dump())
    db.add(category)
    _commit(db, "A category with this name and direction already exists")
    db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=CategoryRead)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    category = _owned_category(db, user.id, category_id, lock=True)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, key, value)
    _commit(db, "A category with this name and direction already exists")
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", response_model=CategoryRead)
def deactivate_category(category_id: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    category = _owned_category(db, user.id, category_id, lock=True)
    category.is_active = False
    db.commit()
    db.refresh(category)
    return category


@router.get("/payment-methods", response_model=PaymentMethodListResponse)
def list_payment_methods(
    request: Request,
    account_role: str | None = Query(default=None, pattern="^(cash|liability|investment)$"),
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    filters = [PaymentMethod.user_id == user.id]
    if account_role is not None:
        filters.append(PaymentMethod.account_role == account_role)
    if is_active is not None:
        filters.append(PaymentMethod.is_active == is_active)
    total = db.scalar(select(func.count(PaymentMethod.id)).where(*filters)) or 0
    items = db.scalars(
        select(PaymentMethod)
        .where(*filters)
        .order_by(
            case(
                (PaymentMethod.account_role == "cash", 0),
                (PaymentMethod.account_role == "investment", 1),
                (PaymentMethod.account_role == "liability", 2),
                else_=3,
            ),
            PaymentMethod.sort_order,
            PaymentMethod.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    transaction_balances = _transaction_balance_totals(db, user.id)
    payloads = []
    for method in items:
        item = PaymentMethodRead.model_validate(method).model_dump()
        if method.track_balance:
            item["effective_balance_cents"] = int(method.current_balance_cents or 0)
            item["balance_source"] = "tracked"
        else:
            item["effective_balance_cents"] = transaction_balances.get(method.id, 0)
            item["balance_source"] = "transactions"
        payloads.append(item)
    return PaymentMethodListResponse(items=payloads, total=total, page=page, page_size=page_size)


@router.post("/payment-methods", response_model=PaymentMethodRead, status_code=status.HTTP_201_CREATED)
def create_payment_method(
    payload: PaymentMethodCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    values = payload.model_dump()
    values["track_balance"] = True
    method = PaymentMethod(user_id=user.id, **values)
    db.add(method)
    _commit(db, "A payment method with this name already exists")
    db.refresh(method)
    return method


@router.patch("/payment-methods/{method_id}", response_model=PaymentMethodRead)
def update_payment_method(
    method_id: int,
    payload: PaymentMethodUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    method = _owned_method(db, user.id, method_id, lock=True)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(method, key, value)
    method.track_balance = True
    _commit(db, "A payment method with this name already exists")
    db.refresh(method)
    return method


@router.delete("/payment-methods/{method_id}", response_model=PaymentMethodRead)
def deactivate_payment_method(method_id: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    method = _owned_method(db, user.id, method_id, lock=True)
    method.is_active = False
    db.commit()
    db.refresh(method)
    return method


@router.get("/transactions", response_model=TransactionListResponse)
def list_transactions(
    request: Request,
    kind: str | None = Query(default=None, pattern="^(cashflow|transfer)$"),
    direction: str | None = Query(default=None, pattern="^(income|expense)$"),
    category_id: int | None = Query(default=None, gt=0),
    payment_method_id: int | None = Query(default=None, gt=0),
    partner_id: int | None = Query(default=None, gt=0),
    transaction_status: str | None = Query(default=None, alias="status", pattern="^(normal|voided)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    filters = [Transaction.user_id == user.id]
    if kind is not None:
        filters.append(Transaction.kind == kind)
    if direction is not None:
        filters.append(Transaction.direction == direction)
    if category_id is not None:
        filters.append(Transaction.category_id == category_id)
    if payment_method_id is not None:
        filters.append(
            or_(
                Transaction.payment_method_id == payment_method_id,
                Transaction.transfer_payment_method_id == payment_method_id,
            )
        )
    if partner_id is not None:
        # Partner ownership is checked before using the id as a filter.  This
        # avoids turning a cross-tenant id into a confusing empty result and
        # keeps the query safe for legacy transactions with dangling ids.
        _owned_partner(db, user.id, partner_id)
        filters.append(Transaction.partner_id == partner_id)
    if transaction_status is not None:
        filters.append(Transaction.status == transaction_status)
    if start_date is not None:
        start_boundary, _ = utc_bounds_for_business_date(start_date)
        filters.append(Transaction.occurred_at >= start_boundary)
    if end_date is not None:
        _, end_boundary = utc_bounds_for_business_date(end_date)
        filters.append(Transaction.occurred_at < end_boundary)

    total = db.scalar(select(func.count(Transaction.id)).where(*filters)) or 0
    transfer_method = aliased(PaymentMethod)
    rows = db.execute(
        select(Transaction, Category.name, PaymentMethod.name, transfer_method.name, Partner.name)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .join(PaymentMethod, Transaction.payment_method_id == PaymentMethod.id)
        .outerjoin(transfer_method, Transaction.transfer_payment_method_id == transfer_method.id)
        .outerjoin(
            Partner,
            (Partner.id == Transaction.partner_id) & (Partner.user_id == user.id),
        )
        .where(*filters)
        .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        _transaction_payload(tx, category_name, method_name, transfer_method_name, partner_name)
        for tx, category_name, method_name, transfer_method_name, partner_name in rows
    ]
    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)


def _cashflow_totals(db: Session, user_id: int) -> TransactionTotalsResponse:
    """All-time income/expense totals; voided entries and transfers excluded."""

    rows = db.execute(
        select(
            Transaction.direction,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount_cents), 0),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.status == "normal",
            Transaction.kind == "cashflow",
        )
        .group_by(Transaction.direction)
    ).all()
    totals = {direction: (int(count), int(amount)) for direction, count, amount in rows}
    income_count, income_cents = totals.get("income", (0, 0))
    expense_count, expense_cents = totals.get("expense", (0, 0))
    return TransactionTotalsResponse(
        income_cents=income_cents,
        expense_cents=expense_cents,
        income_count=income_count,
        expense_count=expense_count,
    )


# Registered before ``/transactions/{transaction_id}`` so the literal
# ``summary`` segment is not captured as a transaction id.
@router.get("/transactions/summary", response_model=TransactionTotalsResponse)
def transactions_summary(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    return _cashflow_totals(db, user.id)


@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
def get_transaction(transaction_id: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    transfer_method = aliased(PaymentMethod)
    row = db.execute(
        select(Transaction, Category.name, PaymentMethod.name, transfer_method.name, Partner.name)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .join(PaymentMethod, Transaction.payment_method_id == PaymentMethod.id)
        .outerjoin(transfer_method, Transaction.transfer_payment_method_id == transfer_method.id)
        .outerjoin(
            Partner,
            (Partner.id == Transaction.partner_id) & (Partner.user_id == user.id),
        )
        .where(Transaction.id == transaction_id, Transaction.user_id == user.id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return _transaction_payload(row[0], row[1], row[2], row[3], row[4])


@router.post("/transactions", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    # A partner id is a tenant-scoped reference.  The old schema deliberately
    # has no FK on transactions.partner_id, so validate it at the API boundary
    # instead of allowing cross-user or dangling new associations.
    validate_partner_reference(db, user.id, payload.partner_id)
    category = _owned_optional_category(db, user.id, payload.category_id)
    method, transfer_method = _owned_method_pair(
        db,
        user.id,
        payload.payment_method_id,
        payload.transfer_payment_method_id,
        lock=True,
    )
    _validate_transaction_dictionaries(
        kind=payload.kind,
        direction=payload.direction,
        category=category,
        method=method,
        transfer_method=transfer_method,
    )
    if payload.source not in {"manual", "ai"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid transaction source")

    transaction = Transaction(
        user_id=user.id,
        occurred_at=_as_utc(payload.occurred_at),
        **payload.model_dump(exclude={"occurred_at"}),
    )
    _apply_transaction_balance(transaction, method, transfer_method)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return _transaction_payload(
        transaction,
        category.name if category else None,
        method.name,
        transfer_method.name if transfer_method else None,
    )


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    transaction = _owned_transaction(db, user.id, transaction_id, lock=True)
    if transaction.status == "voided":
        raise HTTPException(status.HTTP_409_CONFLICT, "Voided transactions cannot be edited")

    changes = payload.model_dump(exclude_unset=True)
    if "occurred_at" in changes:
        # A null PATCH value is not a meaningful timestamp; retain the old
        # value rather than writing NULL into the non-nullable column.
        if changes["occurred_at"] is None:
            changes.pop("occurred_at")
        else:
            changes["occurred_at"] = _as_utc(changes["occurred_at"])

    # A linked partner-ledger entry and its cash transaction form one audited
    # business event.  Protect only *actual* changes to the coupled values.
    # Full edit forms commonly PATCH the current amount/direction/partner again
    # while changing an unrelated field such as category; field presence alone
    # must not turn that safe edit into a conflict.
    protected_changed = (
        ("amount_cents" in changes and changes["amount_cents"] != transaction.amount_cents)
        or ("direction" in changes and changes["direction"] != transaction.direction)
        or ("partner_id" in changes and changes["partner_id"] != transaction.partner_id)
    )
    if has_active_transaction_ledger(db, user.id, transaction.id) and protected_changed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "关联往来流水的现金记录不能单独修改金额、收支方向或往来账户。",
        )

    old_method, old_transfer_method = _owned_method_pair(
        db,
        user.id,
        transaction.payment_method_id,
        transaction.transfer_payment_method_id,
        lock=True,
    )
    _apply_transaction_balance(transaction, old_method, old_transfer_method, reverse=True)

    new_kind = changes.get("kind", transaction.kind)
    new_direction = changes.get("direction", transaction.direction)
    new_category_id = changes.get("category_id", transaction.category_id)
    new_method_id = changes.get("payment_method_id", transaction.payment_method_id)
    new_transfer_method_id = changes.get("transfer_payment_method_id", transaction.transfer_payment_method_id)
    if new_kind == "cashflow":
        new_transfer_method_id = None
        changes["transfer_payment_method_id"] = None
    elif new_kind == "transfer":
        new_direction = "expense"
        changes["direction"] = "expense"
    # Do not reinterpret a legacy partner_id on an old transaction; only a
    # newly supplied association must resolve to a canonical partner row.
    if "partner_id" in changes:
        validate_partner_reference(db, user.id, changes.get("partner_id"))
    category = _owned_optional_category(db, user.id, new_category_id)
    method, transfer_method = _owned_method_pair(
        db,
        user.id,
        new_method_id,
        new_transfer_method_id,
        lock=True,
    )
    _validate_transaction_dictionaries(
        kind=new_kind,
        direction=new_direction,
        category=category,
        method=method,
        transfer_method=transfer_method,
    )
    if changes.get("source", transaction.source) not in {"manual", "ai"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid transaction source")

    for key, value in changes.items():
        setattr(transaction, key, value)
    _apply_transaction_balance(transaction, method, transfer_method)
    db.commit()
    db.refresh(transaction)
    return _transaction_payload(
        transaction,
        category.name if category else None,
        method.name,
        transfer_method.name if transfer_method else None,
    )


@router.post("/transactions/{transaction_id}/void", response_model=TransactionRead)
def void_transaction(
    transaction_id: int,
    request: Request,
    payload: TransactionVoidRequest | None = None,
    db: Session = Depends(get_db),
):
    user = _user(request, db)
    transaction = _owned_transaction(db, user.id, transaction_id, lock=True)
    if transaction.status == "voided":
        raise HTTPException(status.HTTP_409_CONFLICT, "Transaction is already voided")
    method, transfer_method = _owned_method_pair(
        db,
        user.id,
        transaction.payment_method_id,
        transaction.transfer_payment_method_id,
        lock=True,
    )
    category = _owned_optional_category(db, user.id, transaction.category_id)
    _apply_transaction_balance(transaction, method, transfer_method, reverse=True)
    # Any active partner movements linked to this transaction are reversed by
    # compensating ledger rows in the same SQLAlchemy transaction.  If the
    # reversal fails, no status or payment balance is committed.
    reverse_transaction_ledgers(
        db,
        user.id,
        transaction,
        reason=(payload.reason.strip() if payload and payload.reason else None),
    )
    transaction.status = "voided"
    transaction.voided_at = datetime.now(timezone.utc)
    transaction.void_reason = payload.reason.strip() if payload and payload.reason else None
    db.commit()
    db.refresh(transaction)
    return _transaction_payload(
        transaction,
        category.name if category else None,
        method.name,
        transfer_method.name if transfer_method else None,
    )
