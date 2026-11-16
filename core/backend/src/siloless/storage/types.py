"""Column types."""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from siloless.clock import ensure_utc


class UtcDateTime(TypeDecorator[datetime]):
    """A datetime that is always timezone-aware UTC outside the database.

    SQLite drops time zones, so values are stored as naive UTC. Naive values are
    rejected on the way in, and values come back timezone-aware on the way out.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)
