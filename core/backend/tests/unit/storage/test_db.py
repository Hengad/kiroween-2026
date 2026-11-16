from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from siloless.storage.db import Database
from siloless.storage.models import MembershipRow, PrincipalRow


def _anna() -> PrincipalRow:
    return PrincipalRow(id="user:anna", type="user", name="Anna")


def test_a_write_transaction_commits_when_the_block_succeeds(db: Database) -> None:
    with db.transaction() as session:
        session.add(_anna())

    with db.transaction(write=False) as session:
        assert session.get(PrincipalRow, "user:anna") is not None


def test_a_write_transaction_rolls_back_when_the_block_raises(db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction() as session:
        session.add(_anna())
        session.flush()
        raise RuntimeError("boom")

    with db.transaction(write=False) as session:
        assert session.get(PrincipalRow, "user:anna") is None


def test_foreign_keys_are_enforced(db: Database) -> None:
    with pytest.raises(IntegrityError), db.transaction() as session:
        session.add(MembershipRow(user_id="user:ghost", target_id="group:nowhere"))


def test_file_databases_use_write_ahead_logging(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'engine.db'}")
    database.create_schema()

    with database.transaction(write=False) as session:
        mode = session.execute(text("PRAGMA journal_mode")).scalar_one()

    database.dispose()
    assert str(mode).lower() == "wal"


def test_a_write_transaction_takes_the_write_lock_immediately(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'engine.db'}"
    first = Database(url, busy_timeout_ms=100)
    first.create_schema()
    second = Database(url, busy_timeout_ms=100)

    # `first` has not written anything yet. With a deferred BEGIN it would not
    # hold the lock, and `second` could start writing.
    with first.transaction(write=True):
        with pytest.raises(OperationalError), second.transaction(write=True):
            pass

        # Readers are not blocked by the writer.
        with second.transaction(write=False) as session:
            assert session.execute(select(PrincipalRow)).all() is not None

    first.dispose()
    second.dispose()
