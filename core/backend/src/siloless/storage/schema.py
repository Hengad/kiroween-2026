"""Installs everything the ORM metadata cannot express: the search index, event-log
triggers and seed rows. SQLite-specific. A PostgreSQL port replaces this module."""

from sqlalchemy import text
from sqlalchemy.engine import Connection

from siloless.storage.models import Base

_STATEMENTS = (
    # Full-text index. rowid matches the rowid of record_versions.
    "CREATE VIRTUAL TABLE IF NOT EXISTS record_fts USING fts5(title, content)",
    # The event log is append-only. The repository has no update or delete either.
    """
    CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END
    """,
    # The built-in group every user belongs to.
    """
    INSERT OR IGNORE INTO principals (id, type, name)
    VALUES ('group:everyone', 'group', 'Everyone')
    """,
)


def install_schema(connection: Connection) -> None:
    """Create tables, the search index, event triggers and seed rows. Safe to repeat."""
    Base.metadata.create_all(connection)
    for statement in _STATEMENTS:
        connection.execute(text(statement))
