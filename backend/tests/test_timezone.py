from datetime import date, datetime, timezone

from app.timezone import (
    BUSINESS_TZ,
    business_date,
    to_business,
    to_utc,
    utc_bounds_for_business_date,
)


def test_beijing_business_day_maps_to_utc_half_open_bounds():
    start, end = utc_bounds_for_business_date(date(2026, 8, 3))

    assert start == datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 3, 16, tzinfo=timezone.utc)


def test_business_date_assigns_beijing_calendar_day_to_boundary_instants():
    just_before_midnight = datetime(2026, 8, 2, 15, 59, 59, tzinfo=timezone.utc)
    at_midnight = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)

    assert business_date(just_before_midnight) == date(2026, 8, 2)
    assert business_date(at_midnight) == date(2026, 8, 3)


def test_explicit_beijing_wall_clock_is_stored_as_utc_instant():
    wall_clock = datetime(2026, 8, 3, 9, 30, tzinfo=BUSINESS_TZ)

    assert to_utc(wall_clock) == datetime(2026, 8, 3, 1, 30, tzinfo=timezone.utc)
    assert to_business(to_utc(wall_clock)) == wall_clock


def test_legacy_naive_timestamp_remains_utc_while_business_conversion_is_explicit():
    naive_utc = datetime(2026, 8, 3, 1, 30)

    assert to_utc(naive_utc) == datetime(2026, 8, 3, 1, 30, tzinfo=timezone.utc)
    assert to_business(naive_utc).date() == date(2026, 8, 3)
