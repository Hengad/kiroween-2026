"""Database engine and transactions."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from siloless.storage.schema import install_schema


class Database:
    """Owns the engine and hands out transactions.

    Write transactions start with BEGIN IMMEDIATE, so two writers queue instead of
    failing late with a lock-upgrade error. Read transactions use a deferred BEGIN
    and are not blocked by a writer (file databases run in WAL mode).
    """

    def __init__(self, url: str, *, busy_timeout_ms: int = 5000) -> None:
        self._is_memory = url in ("sqlite://", "sqlite:///:memory:")
        if self._is_memory:
            self._engine = create_engine(
                "sqlite://",
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        else:
            self._engine = create_engine(url, connect_args={"check_same_thread": False})
        self._busy_timeout_ms = busy_timeout_ms
        self._install_sqlite_hooks()
        self._write_engine = self._engine.execution_options(sqlite_write=True)
        self._read_engine = self._engine.execution_options(sqlite_write=False)

    @classmethod
    def in_memory(cls) -> "Database":
        return cls("sqlite://")

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_schema(self) -> None:
        with self._engine.begin() as connection:
            install_schema(connection)

    def dispose(self) -> None:
        self._engine.dispose()

    @contextmanager
    def transaction(self, write: bool = True) -> Iterator[Session]:
        """Run a block in one transaction. Commits on success, rolls back on error."""
        engine = self._write_engine if write else self._read_engine
        session = Session(engine, expire_on_commit=False)
        try:
            # Start the transaction now, so a write transaction takes its lock now.
            session.connection()
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def _install_sqlite_hooks(self) -> None:
        busy_timeout_ms = self._busy_timeout_ms
        is_memory = self._is_memory

        @event.listens_for(self._engine, "connect")
        def on_connect(dbapi_connection: Any, _record: Any) -> None:
            # Take transaction control away from pysqlite so BEGIN is explicit.
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
            if not is_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        @event.listens_for(self._engine, "begin")
        def on_begin(connection: Any) -> None:
            write = connection.get_execution_options().get("sqlite_write", True)
            connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
