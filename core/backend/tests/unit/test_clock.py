from datetime import UTC, datetime, timedelta, timezone

import pytest

from siloless.clock import ManualClock, SystemClock, ensure_utc


def test_manual_clock_returns_its_start_time_until_advanced() -> None:
    start = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    clock = ManualClock(start)

    assert clock.now() == start
    assert clock.now() == start


def test_manual_clock_moves_forward_only_when_advanced() -> None:
    start = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    clock = ManualClock(start)

    clock.advance(timedelta(seconds=90))

    assert clock.now() == start + timedelta(seconds=90)


def test_manual_clock_rejects_a_naive_start_time() -> None:
    with pytest.raises(ValueError):
        ManualClock(datetime(2026, 11, 14, 12, 0))


def test_system_clock_returns_timezone_aware_utc() -> None:
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_ensure_utc_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 11, 14, 12, 0))


def test_ensure_utc_converts_other_time_zones_to_utc() -> None:
    helsinki = timezone(timedelta(hours=2))
    value = datetime(2026, 11, 14, 14, 0, tzinfo=helsinki)

    result = ensure_utc(value)

    assert result == datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert result.tzinfo == UTC
