from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from siloless.clock import ManualClock
from siloless.ids import UlidGenerator
from siloless.storage.db import Database


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(datetime(2026, 11, 14, 12, 0, tzinfo=UTC))


@pytest.fixture
def ids(clock: ManualClock) -> UlidGenerator:
    return UlidGenerator(clock)


@pytest.fixture
def db() -> Iterator[Database]:
    database = Database.in_memory()
    database.create_schema()
    yield database
    database.dispose()
