from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from siloless.storage.db import Database
from siloless.storage.migrate import downgrade, upgrade


def url_for(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def schema_of(url: str) -> list[tuple[str, str, str]]:
    """Every table, index, trigger and view, with its SQL, ignoring migration bookkeeping
    and the shadow tables SQLite creates for the search index."""
    engine = create_engine(url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT type, name, COALESCE(sql, '') FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'record_fts_%' "
                "AND name != 'alembic_version' "
                "ORDER BY type, name"
            )
        ).all()
    engine.dispose()
    return [(r[0], r[1], " ".join(r[2].split())) for r in rows]


def seeded_principals(url: str) -> list[str]:
    engine = create_engine(url)
    with engine.connect() as connection:
        ids = list(connection.execute(text("SELECT id FROM principals ORDER BY id")).scalars())
    engine.dispose()
    return ids


def test_the_migration_builds_the_same_schema_as_the_application(tmp_path: Path) -> None:
    app_url = url_for(tmp_path / "app.db")
    migrated_url = url_for(tmp_path / "migrated.db")
    database = Database(app_url)
    database.create_schema()
    database.dispose()

    upgrade(migrated_url)

    assert schema_of(migrated_url) == schema_of(app_url)
    assert seeded_principals(migrated_url) == seeded_principals(app_url) == ["group:everyone"]


def test_the_migration_creates_the_search_index_and_the_event_log_guards(tmp_path: Path) -> None:
    url = url_for(tmp_path / "migrated.db")

    upgrade(url)

    names = {name for _, name, _ in schema_of(url)}
    assert {"record_fts", "events_no_update", "events_no_delete"} <= names


def test_upgrading_twice_is_harmless(tmp_path: Path) -> None:
    url = url_for(tmp_path / "migrated.db")

    upgrade(url)
    upgrade(url)

    assert "events" in {name for _, name, _ in schema_of(url)}


def test_a_database_made_by_the_application_can_be_adopted_by_migrations(
    tmp_path: Path,
) -> None:
    url = url_for(tmp_path / "app.db")
    database = Database(url)
    database.create_schema()
    database.dispose()
    before = schema_of(url)

    upgrade(url)

    assert schema_of(url) == before


@pytest.mark.parametrize("target", ["base"])
def test_downgrading_to_base_removes_everything(tmp_path: Path, target: str) -> None:
    url = url_for(tmp_path / "migrated.db")
    upgrade(url)

    downgrade(url, target)

    assert schema_of(url) == []
