"""PennyPilot's time-zone contract.

The database and timestamp API keep using UTC instants.  Business dates are
different: bookkeeping users operate in Beijing time (UTC+08:00), so a
natural day, relative phrase such as ``昨天``, and a daily settlement all use
``Asia/Shanghai`` boundaries.  Keeping the conversion in one module avoids
subtle differences between transactions, current-account ledgers, reports,
and the settlement worker.

Naive datetimes are interpreted as UTC by :func:`to_utc` for backwards
compatibility with the first API version and with historical SQLite fixtures.
New browser clients send an explicit offset/``Z`` timestamp, so this policy
does not discard a user's Beijing wall-clock time.  Callers parsing a local
wall-clock value should attach :data:`BUSINESS_TZ` before calling
:func:`to_utc`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc
BUSINESS_TIMEZONE_NAME = "Asia/Shanghai"
BUSINESS_TZ = ZoneInfo(BUSINESS_TIMEZONE_NAME)
# A descriptive alias makes call sites that explicitly discuss Beijing easy
# to read while retaining one ZoneInfo instance.
BEIJING_TZ = BUSINESS_TZ


def now_utc() -> datetime:
    """Return the current aware UTC instant used for persistence."""

    return datetime.now(UTC)


def now_business() -> datetime:
    """Return the current aware Beijing wall-clock time."""

    return now_utc().astimezone(BUSINESS_TZ)


def to_utc(value: datetime | None, *, assume_naive: timezone | ZoneInfo = UTC) -> datetime:
    """Normalize a datetime to an aware UTC instant.

    ``None`` means *now* and is useful for optional ``occurred_at`` fields.
    A naive value is assigned ``assume_naive`` rather than being silently
    shifted.  The default is UTC to preserve the legacy API contract; callers
    handling a Beijing wall-clock input can pass ``assume_naive=BUSINESS_TZ``.
    """

    if value is None:
        return now_utc()
    if value.tzinfo is None:
        value = value.replace(tzinfo=assume_naive)
    return value.astimezone(UTC)


def to_business(value: datetime | None, *, assume_naive: timezone | ZoneInfo = UTC) -> datetime:
    """Normalize a datetime to an aware ``Asia/Shanghai`` datetime."""

    return to_utc(value, assume_naive=assume_naive).astimezone(BUSINESS_TZ)


def business_today() -> date:
    """Return today's calendar date in Beijing."""

    return now_business().date()


def business_date(value: datetime | date | None = None) -> date:
    """Return the Beijing calendar date for a datetime or current instant."""

    if value is None:
        return business_today()
    if isinstance(value, datetime):
        return to_business(value).date()
    return value


def utc_bounds_for_business_date(value: date) -> tuple[datetime, datetime]:
    """Return the UTC half-open bounds for one Beijing natural day.

    For example, ``2026-08-03`` maps to ``2026-08-02 16:00Z`` through
    ``2026-08-03 16:00Z``.  Returning UTC-aware values keeps SQL comparisons
    index-friendly and leaves the persisted/API timestamp contract unchanged.
    """

    local_start = datetime.combine(value, time.min, tzinfo=BUSINESS_TZ)
    next_local_start = datetime.combine(value + timedelta(days=1), time.min, tzinfo=BUSINESS_TZ)
    return local_start.astimezone(UTC), next_local_start.astimezone(UTC)


def business_day_start_utc(value: date) -> datetime:
    """Return the UTC instant at Beijing midnight for ``value``."""

    return utc_bounds_for_business_date(value)[0]


def business_day_end_utc(value: date) -> datetime:
    """Return the exclusive UTC instant at the next Beijing midnight."""

    return utc_bounds_for_business_date(value)[1]

