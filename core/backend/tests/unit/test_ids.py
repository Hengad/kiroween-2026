from datetime import UTC, datetime, timedelta

from siloless.clock import ManualClock
from siloless.ids import UlidGenerator

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def _generator(start: datetime | None = None) -> tuple[UlidGenerator, ManualClock]:
    clock = ManualClock(start or datetime(2026, 11, 14, 12, 0, tzinfo=UTC))
    return UlidGenerator(clock, random_bytes=lambda n: bytes(range(n))), clock


def test_ulid_is_26_crockford_characters() -> None:
    generator, _ = _generator()

    value = generator.new()

    assert len(value) == 26
    assert set(value) <= CROCKFORD


def test_ids_created_in_the_same_millisecond_still_sort_in_creation_order() -> None:
    generator, _ = _generator()

    ids = [generator.new() for _ in range(500)]

    assert ids == sorted(ids)
    assert len(set(ids)) == 500


def test_ids_sort_by_time_across_milliseconds() -> None:
    generator, clock = _generator()
    first = generator.new()

    clock.advance(timedelta(milliseconds=5))
    second = generator.new()

    assert first < second


def test_ids_stay_ordered_if_the_clock_moves_backwards() -> None:
    generator, clock = _generator()
    first = generator.new()

    clock.advance(timedelta(seconds=-10))
    second = generator.new()

    assert first < second


def test_ids_are_unique_when_random_bytes_are_constant() -> None:
    generator = UlidGenerator(
        ManualClock(datetime(2026, 11, 14, 12, 0, tzinfo=UTC)),
        random_bytes=lambda n: b"\xff" * n,
    )

    ids = [generator.new() for _ in range(5)]

    assert len(set(ids)) == 5
    assert ids == sorted(ids)
