"""Daily settlement snapshot service and authenticated API.

Snapshots are reports derived from immutable transactions and partner ledger
movements.  A normal run is idempotent; only the explicit recalculation route
updates an existing row.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import DailySnapshot, Partner, PartnerLedgerEntry, Transaction, User
from .settlement_schemas import (
    DailySnapshotListResponse,
    DailySnapshotRead,
    SettlementRecalculateRequest,
    SettlementRecalculateResponse,
    SettlementRunRequest,
)
from .timezone import (
    UTC,
    business_today,
    to_utc,
    utc_bounds_for_business_date,
)


router = APIRouter(prefix="/api", tags=["settlements"])


def _as_utc(value: datetime | None) -> datetime:
    """Return an aware UTC instant for DB/API compatibility."""

    return to_utc(value)


def _day_bounds(settlement_date: date) -> tuple[datetime, datetime]:
    """Return UTC bounds for a Beijing natural day."""

    return utc_bounds_for_business_date(settlement_date)


def _dates_inclusive(start_date: date, end_date: date):
    """Yield a bounded inclusive date range for recalculation backfills."""

    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def previous_settlement_date() -> date:
    """Return the previous Beijing calendar day used by the scheduled job."""

    return business_today() - timedelta(days=1)


def _validate_settlement_date(value: date) -> date:
    if value > previous_settlement_date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Settlement date cannot be in the future or the current day",
        )
    return value


def _ledger_delta(entry: PartnerLedgerEntry) -> dict[str, int]:
    """Interpret a ledger row as signed movement in each account dimension."""

    return {
        "prepaid_balance_cents": int(entry.prepaid_after_cents or 0)
        - int(entry.prepaid_before_cents or 0),
        "credit_limit_cents": int(entry.credit_limit_after_cents or 0)
        - int(entry.credit_limit_before_cents or 0),
        "credit_used_cents": int(entry.credit_used_after_cents or 0)
        - int(entry.credit_used_before_cents or 0),
    }


def _settlement_lock(db: Session, user_id: int, scope: str) -> None:
    """Serialize settlement writers on PostgreSQL.

    The unique user/date key remains the final race guard.  An advisory
    transaction lock keeps a scheduled run, a manual run, and a recalculation
    from interleaving their reads and writes.  SQLite test databases simply
    skip the PostgreSQL-specific statement.
    """

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            # Serialize all settlement writers for a tenant, regardless of
            # whether the caller is a per-day run or a range recalculation.
            # Otherwise a manual run for one date could interleave with a
            # recalc and produce a report from a mixed read snapshot.
            {"lock_key": f"pennypilot:settlement:{user_id}"},
        )


def _asset_contribution(partner_type: str, prepaid: int, credit_used: int) -> int:
    """Apply the plan's total-asset formula for one partner."""

    # Supplier prepaid is our asset; supplier credit used is our payable.
    if partner_type == "supplier":
        return prepaid - credit_used
    # Customer credit used is our receivable; customer prepaid is our liability.
    return credit_used - prepaid


def _calculate_snapshot(
    db: Session, user_id: int, settlement_date: date, *, settled_at: datetime | None = None
) -> dict[str, Any]:
    """Build a complete point-in-time report by replaying signed movements.

    We intentionally do not use a ledger row's ``*_after`` values as the
    historical state.  Rows may be entered with a backdated ``occurred_at``;
    replaying before/after *deltas* in chronological order keeps historical
    snapshots deterministic and makes a later recalculation correct.
    """

    start, end = _day_bounds(settlement_date)
    partners = db.scalars(
        select(Partner).where(Partner.user_id == user_id).order_by(Partner.id)
    ).all()
    entries = db.scalars(
        select(PartnerLedgerEntry)
        .where(PartnerLedgerEntry.user_id == user_id)
        .order_by(PartnerLedgerEntry.id)
    ).all()
    entries_by_partner: dict[int, list[PartnerLedgerEntry]] = defaultdict(list)
    for entry in entries:
        entries_by_partner[entry.partner_id].append(entry)
    for rows in entries_by_partner.values():
        rows.sort(key=lambda item: (_as_utc(item.occurred_at), item.id))

    account_balances: list[dict[str, Any]] = []
    account_changes: list[dict[str, Any]] = []
    partner_asset_total = 0

    for partner in partners:
        rows = entries_by_partner.get(partner.id, [])
        # A row's before-state is an insertion-time snapshot, not necessarily
        # the historical state at its occurred_at (a backdated row may have
        # before=200 even though its signed movement is only +20).  Derive the
        # opening baseline from the current partner state minus the sum of all
        # signed ledger deltas, then replay deltas in chronological
        # (occurred_at, id) order.  This handles both normal API opening rows
        # (baseline zero) and legacy/direct initial balances with later ledger
        # movements, without trusting a stale row.before value.
        if rows:
            total_delta = {
                "prepaid_balance_cents": 0,
                "credit_limit_cents": 0,
                "credit_used_cents": 0,
            }
            for entry in rows:
                delta = _ledger_delta(entry)
                for key in total_delta:
                    total_delta[key] += delta[key]
            state = {
                key: int(getattr(partner, key) or 0) - total_delta[key]
                for key in total_delta
            }
        else:
            created_at = _as_utc(partner.created_at)
            state = {
                "prepaid_balance_cents": int(partner.prepaid_balance_cents or 0)
                if created_at < end
                else 0,
                "credit_limit_cents": int(partner.credit_limit_cents or 0)
                if created_at < end
                else 0,
                "credit_used_cents": int(partner.credit_used_cents or 0)
                if created_at < end
                else 0,
            }
        change = {
            "prepaid_balance_cents": 0,
            "credit_limit_cents": 0,
            "credit_used_cents": 0,
            "ledger_count": 0,
            "ledger_amount_cents": 0,
        }
        for entry in rows:
            occurred_at = _as_utc(entry.occurred_at)
            delta = _ledger_delta(entry)
            if occurred_at < end:
                for key in state:
                    state[key] += delta[key]
            if start <= occurred_at < end:
                for key in change:
                    if key in delta:
                        change[key] += delta[key]
                change["ledger_count"] += 1
                change["ledger_amount_cents"] += int(entry.amount_cents or 0)

        prepaid = state["prepaid_balance_cents"]
        credit_limit = state["credit_limit_cents"]
        credit_used = state["credit_used_cents"]
        is_customer = str(partner.type).lower() == "customer"
        # The current-account module now has one balance concept for both
        # partner types: customers' receivables are credit_used, while
        # suppliers' payables are prepaid.  Keep the legacy dimensions below
        # for old snapshots and asset calculations, but expose the canonical
        # unsettled fields for the new settlement UI.
        unsettled = credit_used if is_customer else prepaid
        # Do not clamp this value: a negative remainder is an important risk
        # signal after a historical reversal or legacy-data correction.
        credit_remaining = credit_limit - credit_used
        asset_contribution = _asset_contribution(partner.type, prepaid, credit_used)
        partner_asset_total += asset_contribution
        account_balances.append(
            {
                "partner_id": partner.id,
                "name": partner.name,
                "type": partner.type,
                "status": partner.status,
                "prepaid_balance_cents": prepaid,
                "credit_limit_cents": credit_limit,
                "credit_used_cents": credit_used,
                "credit_remaining_cents": credit_remaining,
                "unsettled_balance_cents": unsettled,
                "asset_contribution_cents": asset_contribution,
            }
        )
        prepaid_delta = change["prepaid_balance_cents"]
        credit_limit_delta = change["credit_limit_cents"]
        credit_used_delta = change["credit_used_cents"]
        asset_delta = _asset_contribution(
            partner.type, prepaid_delta, credit_used_delta
        )
        unsettled_delta = credit_used_delta if is_customer else prepaid_delta
        account_changes.append(
            {
                "partner_id": partner.id,
                "name": partner.name,
                "type": partner.type,
                "prepaid_delta_cents": prepaid_delta,
                "credit_limit_delta_cents": credit_limit_delta,
                "credit_used_delta_cents": credit_used_delta,
                "unsettled_delta_cents": unsettled_delta,
                "asset_delta_cents": asset_delta,
                "net_delta_cents": asset_delta,
                "ledger_count": change["ledger_count"],
                "ledger_amount_cents": change["ledger_amount_cents"],
            }
        )

    income_cents = 0
    expense_cents = 0
    cumulative_income_cents = 0
    cumulative_expense_cents = 0
    partner_settlement_amounts: dict[int, int] = defaultdict(int)
    partner_settlement_counts: dict[int, int] = defaultdict(int)
    transactions = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.status == "normal",
            Transaction.kind == "cashflow",
        )
    ).all()
    for transaction in transactions:
        occurred_at = _as_utc(transaction.occurred_at)
        amount = int(transaction.amount_cents or 0)
        if occurred_at < end:
            if transaction.direction == "income":
                cumulative_income_cents += amount
            elif transaction.direction == "expense":
                cumulative_expense_cents += amount
        if start <= occurred_at < end:
            if transaction.direction == "income":
                income_cents += amount
            elif transaction.direction == "expense":
                expense_cents += amount
            # A partner's daily settlement amount is the linked cash movement,
            # not the change in its observed unsettled balance.  For example,
            # a customer can pay 10,000 while the user explicitly confirms
            # that the remaining unsettled balance is unchanged or zero.
            if transaction.partner_id is not None:
                signed_amount = amount if transaction.direction == "income" else -amount
                partner_settlement_amounts[int(transaction.partner_id)] += signed_amount
                partner_settlement_counts[int(transaction.partner_id)] += 1

    for change in account_changes:
        partner_id = int(change["partner_id"])
        change["settlement_amount_cents"] = partner_settlement_amounts.get(partner_id, 0)
        change["settlement_count"] = partner_settlement_counts.get(partner_id, 0)

    net_cents = income_cents - expense_cents
    total_assets_cents = (
        cumulative_income_cents
        - cumulative_expense_cents
        + partner_asset_total
    )
    return {
        "user_id": user_id,
        "settlement_date": settlement_date,
        "settled_at": settled_at or datetime.now(UTC),
        "income_cents": income_cents,
        "expense_cents": expense_cents,
        "net_cents": net_cents,
        "total_assets_cents": total_assets_cents,
        "account_balances": account_balances,
        "account_changes": account_changes,
    }


def _snapshot_payload(row: DailySnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "settlement_date": row.settlement_date,
        "settled_at": _as_utc(row.settled_at),
        "income_cents": row.income_cents,
        "expense_cents": row.expense_cents,
        "net_cents": row.net_cents,
        "total_assets_cents": row.total_assets_cents,
        "account_balances": row.account_balances or [],
        "account_changes": row.account_changes or [],
        "is_recalculated": bool(row.is_recalculated),
        "is_live": False,
        "recalculated_at": _as_utc(row.recalculated_at)
        if row.recalculated_at is not None
        else None,
        "created_at": _as_utc(row.created_at),
    }


def _live_snapshot_payload(user_id: int, settlement_date: date, values: dict[str, Any]) -> dict[str, Any]:
    """Return a non-persistent preview for the currently open Beijing day."""

    now = datetime.now(UTC)
    return {
        "id": 0,
        "user_id": user_id,
        "settlement_date": settlement_date,
        "settled_at": now,
        "income_cents": values["income_cents"],
        "expense_cents": values["expense_cents"],
        "net_cents": values["net_cents"],
        "total_assets_cents": values["total_assets_cents"],
        "account_balances": values["account_balances"],
        "account_changes": values["account_changes"],
        "is_recalculated": False,
        "is_live": True,
        "recalculated_at": None,
        "created_at": now,
    }


def _update_snapshot(row: DailySnapshot, values: dict[str, Any], *, recalculated: bool) -> None:
    for key in (
        "settled_at",
        "income_cents",
        "expense_cents",
        "net_cents",
        "total_assets_cents",
        "account_balances",
        "account_changes",
    ):
        setattr(row, key, values[key])
    if recalculated:
        row.is_recalculated = True
        row.recalculated_at = datetime.now(UTC)


def generate_snapshot(
    db: Session, user_id: int, settlement_date: date, *, idempotent: bool = True
) -> tuple[DailySnapshot, bool]:
    """Create one snapshot and return ``(row, created)``.

    ``idempotent`` is retained as an explicit argument for job callers; the
    public run operation always leaves an existing row untouched.
    """

    _validate_settlement_date(settlement_date)
    _settlement_lock(db, user_id, settlement_date.isoformat())
    existing = db.scalar(
        select(DailySnapshot)
        .where(
            DailySnapshot.user_id == user_id,
            DailySnapshot.settlement_date == settlement_date,
        )
        .with_for_update()
    )
    if existing is not None and idempotent:
        return existing, False
    values = _calculate_snapshot(db, user_id, settlement_date)
    if existing is not None:
        _update_snapshot(existing, values, recalculated=True)
        return existing, False
    row = DailySnapshot(**values)
    db.add(row)
    db.flush()
    return row, True


@router.get("/settlements", response_model=DailySnapshotListResponse)
def list_settlements(
    request: Request,
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=365),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "end_date must be on or after start_date")
    filters = [DailySnapshot.user_id == user.id]
    if start_date is not None:
        filters.append(DailySnapshot.settlement_date >= start_date)
    if end_date is not None:
        filters.append(DailySnapshot.settlement_date <= end_date)
    total = db.scalar(select(func.count(DailySnapshot.id)).where(*filters)) or 0
    rows = db.scalars(
        select(DailySnapshot)
        .where(*filters)
        .order_by(DailySnapshot.settlement_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [_snapshot_payload(row) for row in rows]
    current_day = business_today()
    current_in_range = (start_date is None or current_day >= start_date) and (end_date is None or current_day <= end_date)
    if current_in_range and not any(row.settlement_date == current_day for row in rows):
        items.append(_live_snapshot_payload(user.id, current_day, _calculate_snapshot(db, user.id, current_day)))
        items.sort(key=lambda item: str(item["settlement_date"]), reverse=True)
        total += 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/settlements/{settlement_date}", response_model=DailySnapshotRead)
def get_settlement(
    settlement_date: date, request: Request, db: Session = Depends(get_db)
):
    user = current_user(request, db)
    row = db.scalar(
        select(DailySnapshot).where(
            DailySnapshot.user_id == user.id,
            DailySnapshot.settlement_date == settlement_date,
        )
    )
    if row is None:
        if settlement_date == business_today():
            return _live_snapshot_payload(
                user.id,
                settlement_date,
                _calculate_snapshot(db, user.id, settlement_date),
            )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Settlement snapshot not found")
    return _snapshot_payload(row)


@router.post("/settlements/run", response_model=DailySnapshotRead)
def run_settlement(
    payload: SettlementRunRequest | None = None,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    if request is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = current_user(request, db)
    settlement_date = _validate_settlement_date(
        payload.settlement_date if payload and payload.settlement_date else previous_settlement_date()
    )
    try:
        row, _ = generate_snapshot(db, user.id, settlement_date, idempotent=True)
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.scalar(
            select(DailySnapshot).where(
                DailySnapshot.user_id == user.id,
                DailySnapshot.settlement_date == settlement_date,
            )
        )
        if row is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Could not create settlement snapshot")
    db.refresh(row)
    return _snapshot_payload(row)


@router.post(
    "/settlements/recalculate",
    response_model=SettlementRecalculateResponse,
)
def recalculate_settlements(
    payload: SettlementRecalculateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    from_date = _validate_settlement_date(payload.from_date)
    _settlement_lock(
        db,
        user.id,
        f"recalculate:{payload.from_date.isoformat()}:{payload.to_date.isoformat() if payload.to_date else 'latest'}",
    )
    latest_existing = db.scalar(
        select(func.max(DailySnapshot.settlement_date)).where(
            DailySnapshot.user_id == user.id,
            DailySnapshot.settlement_date >= from_date,
        )
    )
    to_date = payload.to_date or latest_existing or previous_settlement_date()
    to_date = _validate_settlement_date(to_date)
    if to_date < from_date:
        return {
            "from_date": from_date,
            "to_date": to_date,
            "recalculated_count": 0,
            "created_count": 0,
            "items": [],
        }
    if (to_date - from_date).days > 3660:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Recalculation range cannot exceed 10 years",
        )
    rows = db.scalars(
        select(DailySnapshot)
        .where(
            DailySnapshot.user_id == user.id,
            DailySnapshot.settlement_date >= from_date,
            DailySnapshot.settlement_date <= to_date,
        )
        .order_by(DailySnapshot.settlement_date)
        .with_for_update()
    ).all()
    rows_by_date = {row.settlement_date: row for row in rows}
    now = datetime.now(UTC)
    recalculated_count = 0
    created_count = 0
    # Recalculate existing days and fill gaps in the requested range.  Filling
    # gaps makes recovery after a missed timer run deterministic; an explicit
    # range is still bounded above to avoid accidental multi-decade writes.
    for current_date in _dates_inclusive(from_date, to_date):
        row = rows_by_date.get(current_date)
        values = _calculate_snapshot(db, user.id, current_date, settled_at=now)
        if row is None:
            row = DailySnapshot(
                **values,
                is_recalculated=True,
                recalculated_at=now,
            )
            db.add(row)
            db.flush()
            rows.append(row)
            rows_by_date[current_date] = row
            created_count += 1
        else:
            _update_snapshot(row, values, recalculated=True)
            recalculated_count += 1
    db.commit()
    rows.sort(key=lambda item: item.settlement_date)
    for row in rows:
        db.refresh(row)
    return {
        "from_date": from_date,
        "to_date": to_date,
        "recalculated_count": recalculated_count,
        "created_count": created_count,
        "items": [_snapshot_payload(row) for row in rows],
    }
