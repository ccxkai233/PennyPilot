"""CLI entry point for the daily settlement timer.

Run from the backend virtual environment::

    python -m app.settlement_job --previous-day

The job is deliberately a small synchronous process so it can be supervised
by systemd/cron independently from web worker lifecycles.  Each user is
committed independently; a failure for one tenant does not roll back already
completed tenants.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import SessionLocal
from .models import DailySnapshot, User
from .settlements import generate_snapshot, previous_settlement_date


def run_all_users(target_date: date) -> dict[str, int | str]:
    """Generate an idempotent snapshot for every active user."""

    created = 0
    existing = 0
    failed = 0
    with SessionLocal() as db:
        user_ids = db.scalars(select(User.id).where(User.is_active.is_(True))).all()
    for user_id in user_ids:
        with SessionLocal() as db:
            try:
                row, was_created = generate_snapshot(db, user_id, target_date)
                db.commit()
                if was_created:
                    created += 1
                else:
                    existing += 1
            except IntegrityError:
                # Another timer/worker may have won the unique (user,date)
                # race.  Treat that as idempotent success after rollback.
                db.rollback()
                row = db.scalar(
                    select(DailySnapshot).where(
                        DailySnapshot.user_id == user_id,
                        DailySnapshot.settlement_date == target_date,
                    )
                )
                if row is not None:
                    existing += 1
                else:
                    failed += 1
            except Exception as exc:
                db.rollback()
                failed += 1
                # Keep the error actionable in the systemd journal without
                # dumping request data or secrets.
                print(
                    f"settlement failed for user_id={user_id}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
    return {
        "settlement_date": target_date.isoformat(),
        "users": len(user_ids),
        "created": created,
        "existing": existing,
        "failed": failed,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate PennyPilot daily settlement snapshots")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--previous-day",
        action="store_true",
        help="settle the previous Beijing calendar day (default)",
    )
    group.add_argument(
        "--date",
        dest="settlement_date",
        type=date.fromisoformat,
        help="explicit Beijing settlement date (YYYY-MM-DD)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    target = args.settlement_date or previous_settlement_date()
    if target > previous_settlement_date():
        print(
            "settlement date cannot be today or in the future (Beijing time)",
            file=sys.stderr,
        )
        return 2
    result = run_all_users(target)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result["failed"] else 0


if __name__ == "__main__":  # pragma: no cover - exercised by systemd
    raise SystemExit(main())
