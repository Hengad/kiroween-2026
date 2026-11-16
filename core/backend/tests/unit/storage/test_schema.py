from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from siloless.storage.db import Database
from siloless.storage.models import (
    EntityRow,
    EventRow,
    PrincipalRow,
    RecordRow,
    RecordVersionRow,
    RelationRow,
)

EXPECTED_TABLES = {
    "principals",
    "memberships",
    "records",
    "record_versions",
    "record_version_acl",
    "entities",
    "relations",
    "work_items",
    "work_item_evidence",
    "events",
}


def test_install_schema_creates_every_table(db: Database) -> None:
    tables = set(inspect(db.engine).get_table_names())

    assert tables >= EXPECTED_TABLES


def test_install_schema_seeds_the_everyone_group_and_can_run_twice(db: Database) -> None:
    db.create_schema()

    with db.transaction(write=False) as session:
        everyone = session.get(PrincipalRow, "group:everyone")

    assert everyone is not None
    assert everyone.type == "group"


def test_the_full_text_index_matches_inserted_text(db: Database) -> None:
    with db.transaction() as session:
        session.execute(
            text("INSERT INTO record_fts (rowid, title, content) VALUES (1, :t, :c)"),
            {"t": "Press 3 maintenance", "c": "Replace the hydraulic seal every 500 hours."},
        )

    with db.transaction(write=False) as session:
        hits = session.execute(
            text("SELECT rowid FROM record_fts WHERE record_fts MATCH :q"), {"q": '"hydraulic"'}
        ).all()

    assert [row[0] for row in hits] == [1]


def _event(seq_id: str, when: datetime) -> EventRow:
    return EventRow(
        id=seq_id,
        occurred_at=when,
        type="test.happened",
        actor="system",
        subject_type="record",
        subject_id="r1",
        payload={},
    )


def test_events_cannot_be_updated_or_deleted(db: Database) -> None:
    with db.transaction() as session:
        session.add(_event("01", datetime(2026, 11, 14, 12, 0, tzinfo=UTC)))

    with pytest.raises(DBAPIError, match="append-only"), db.transaction() as session:
        session.execute(text("UPDATE events SET type = 'tampered'"))

    with pytest.raises(DBAPIError, match="append-only"), db.transaction() as session:
        session.execute(text("DELETE FROM events"))


def test_events_get_increasing_sequence_numbers(db: Database) -> None:
    when = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    with db.transaction() as session:
        first, second = _event("01", when), _event("02", when)
        session.add_all([first, second])
        session.flush()

        assert second.seq > first.seq


def test_timestamps_are_stored_in_utc_and_read_back_timezone_aware(db: Database) -> None:
    helsinki = timezone(timedelta(hours=2))
    with db.transaction() as session:
        session.add(_event("01", datetime(2026, 11, 14, 14, 0, tzinfo=helsinki)))

    with db.transaction(write=False) as session:
        stored = session.query(EventRow).one()

    assert stored.occurred_at == datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert stored.occurred_at.tzinfo is not None


def test_naive_timestamps_are_rejected(db: Database) -> None:
    with pytest.raises(Exception, match="timezone-aware"), db.transaction() as session:
        session.add(_event("01", datetime(2026, 11, 14, 12, 0)))
        session.flush()


def _two_entities() -> list[EntityRow]:
    return [
        EntityRow(id="e1", entity_type="machine", key="press-3", name="Press 3", attributes={}),
        EntityRow(id="e2", entity_type="machine", key="press-4", name="Press 4", attributes={}),
    ]


def _add_record_version(session: Session) -> None:
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    session.add(RecordRow(id="rec1", source_id="s", external_id="x", current_version_id="v1"))
    session.flush()
    session.add(
        RecordVersionRow(
            id="v1",
            record_id="rec1",
            version=1,
            kind="doc",
            title="t",
            content="c",
            meta={},
            occurred_at=now,
            ingested_at=now,
            content_hash="h",
        )
    )


def test_a_relation_needs_a_node_on_each_side(db: Database) -> None:
    with db.transaction() as session:
        session.add_all(_two_entities())

    with (
        pytest.raises(IntegrityError, match="ck_relations_from_one_node"),
        db.transaction() as session,
    ):
        session.add(RelationRow(id="r1", relation_type="about", to_entity_id="e2"))


def test_a_relation_cannot_have_two_nodes_on_the_same_side(db: Database) -> None:
    with db.transaction() as session:
        session.add_all(_two_entities())
        _add_record_version(session)

    with (
        pytest.raises(IntegrityError, match="ck_relations_from_one_node"),
        db.transaction() as session,
    ):
        session.add(
            RelationRow(
                id="r1",
                relation_type="about",
                from_entity_id="e1",
                from_version_id="v1",
                to_entity_id="e2",
            )
        )


def test_an_identical_relation_cannot_be_stored_twice(db: Database) -> None:
    with db.transaction() as session:
        session.add_all(_two_entities())
        session.add(
            RelationRow(id="r1", relation_type="about", from_entity_id="e1", to_entity_id="e2")
        )

    with pytest.raises(IntegrityError, match="UNIQUE"), db.transaction() as session:
        session.add(
            RelationRow(id="r2", relation_type="about", from_entity_id="e1", to_entity_id="e2")
        )


def test_a_relation_cannot_point_at_a_missing_node(db: Database) -> None:
    with db.transaction() as session:
        session.add(_two_entities()[0])

    with pytest.raises(IntegrityError, match="FOREIGN KEY"), db.transaction() as session:
        session.add(
            RelationRow(id="r1", relation_type="about", from_entity_id="e1", to_entity_id="missing")
        )
