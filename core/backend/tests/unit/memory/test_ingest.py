from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text

from siloless.access.acl import Acl
from siloless.clock import ManualClock
from siloless.errors import DomainError
from siloless.events.log import EventLog
from siloless.ids import UlidGenerator
from siloless.memory.domain import NewRecord
from siloless.memory.ingest import RecordIngestor
from siloless.settings import Settings
from siloless.storage.db import Database
from siloless.storage.models import (
    EventRow,
    RecordRow,
    RecordVersionAclRow,
    RecordVersionRow,
)


@pytest.fixture
def ingestor(db: Database, clock: ManualClock, ids: UlidGenerator) -> RecordIngestor:
    settings = Settings(_env_file=None, max_record_bytes=2000)
    return RecordIngestor(db, clock, ids, EventLog(clock, ids), settings)


def make_record(**overrides: Any) -> NewRecord:
    base = NewRecord(
        source_id="wiki",
        external_id="press-3-seal",
        kind="procedure",
        title="Press 3 seal replacement",
        content="Replace the hydraulic seal every 500 hours.",
        metadata={"owner": "maintenance"},
        acl=Acl.of("group:maintenance"),
        occurred_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
    )
    return replace(base, **overrides)


def count(db: Database, model: type) -> int:
    with db.transaction(write=False) as session:
        return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_a_new_record_is_stored_as_version_one(ingestor: RecordIngestor, db: Database) -> None:
    result = ingestor.ingest(make_record())

    assert result.created
    assert result.version == 1
    assert len(result.record_id) == 26
    assert len(result.version_id) == 26
    assert count(db, RecordRow) == 1
    assert count(db, RecordVersionRow) == 1


def test_the_acl_and_search_index_are_written_with_the_version(
    ingestor: RecordIngestor, db: Database
) -> None:
    result = ingestor.ingest(make_record(acl=Acl.of("group:maintenance", "user:anna")))

    with db.transaction(write=False) as session:
        entries = set(
            session.execute(
                select(RecordVersionAclRow.principal_id).where(
                    RecordVersionAclRow.version_id == result.version_id
                )
            ).scalars()
        )
        hits = session.execute(
            text(
                "SELECT v.id FROM record_fts f JOIN record_versions v ON v.rowid = f.rowid "
                "WHERE record_fts MATCH :q"
            ),
            {"q": '"hydraulic"'},
        ).all()

    assert entries == {"group:maintenance", "user:anna"}
    assert [row[0] for row in hits] == [result.version_id]


def test_ingesting_the_same_payload_again_changes_nothing(
    ingestor: RecordIngestor, db: Database
) -> None:
    first = ingestor.ingest(make_record())

    second = ingestor.ingest(make_record())

    assert not second.created
    assert second.version_id == first.version_id
    assert second.version == 1
    assert count(db, RecordVersionRow) == 1
    assert count(db, EventRow) == 1


def test_a_different_timestamp_alone_is_not_a_change(
    ingestor: RecordIngestor, db: Database
) -> None:
    ingestor.ingest(make_record())

    again = ingestor.ingest(make_record(occurred_at=datetime(2026, 11, 2, 9, 0, tzinfo=UTC)))

    assert not again.created
    assert count(db, RecordVersionRow) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Press 3 seal replacement (revised)"},
        {"content": "Replace the hydraulic seal every 400 hours."},
        {"metadata": {"owner": "operations"}},
        {"kind": "policy"},
        {"acl": Acl.of("group:management")},
    ],
)
def test_a_change_creates_a_new_version_and_keeps_the_old_one(
    ingestor: RecordIngestor, db: Database, change: dict[str, Any]
) -> None:
    first = ingestor.ingest(make_record())

    second = ingestor.ingest(make_record(**change))

    assert second.created
    assert second.version == 2
    assert second.record_id == first.record_id
    assert second.version_id != first.version_id
    with db.transaction(write=False) as session:
        old = session.get(RecordVersionRow, first.version_id)
        record = session.get(RecordRow, first.record_id)
    assert old is not None
    assert old.title == "Press 3 seal replacement"
    assert old.content == "Replace the hydraulic seal every 500 hours."
    assert record is not None
    assert record.current_version_id == second.version_id


def test_going_back_to_an_earlier_payload_is_a_new_version(
    ingestor: RecordIngestor, db: Database
) -> None:
    ingestor.ingest(make_record())
    ingestor.ingest(make_record(content="Replace the seal every 400 hours."))

    reverted = ingestor.ingest(make_record())

    assert reverted.created
    assert reverted.version == 3
    assert count(db, RecordVersionRow) == 3


def test_the_current_version_is_always_the_newest(ingestor: RecordIngestor, db: Database) -> None:
    result = ingestor.ingest(make_record())
    for hours in (400, 300, 200):
        result = ingestor.ingest(make_record(content=f"Replace the seal every {hours} hours."))

    with db.transaction(write=False) as session:
        record = session.get(RecordRow, result.record_id)
        newest = (
            session.execute(
                select(RecordVersionRow.id)
                .where(RecordVersionRow.record_id == result.record_id)
                .order_by(RecordVersionRow.version.desc())
            )
            .scalars()
            .first()
        )
    assert record is not None
    assert record.current_version_id == newest == result.version_id
    assert result.version == 4


def test_different_items_become_different_records(ingestor: RecordIngestor, db: Database) -> None:
    a = ingestor.ingest(make_record(external_id="a"))
    b = ingestor.ingest(make_record(external_id="b"))
    c = ingestor.ingest(make_record(external_id="a", source_id="other"))

    assert len({a.record_id, b.record_id, c.record_id}) == 3
    assert count(db, RecordRow) == 3


def test_each_new_version_appends_one_event_by_the_system(
    ingestor: RecordIngestor, db: Database, clock: ManualClock
) -> None:
    first = ingestor.ingest(make_record())
    clock.advance(timedelta(minutes=5))
    second = ingestor.ingest(make_record(title="Changed"))

    with db.transaction(write=False) as session:
        events = list(session.execute(select(EventRow).order_by(EventRow.seq)).scalars())

    assert [e.type for e in events] == ["record.version_added"] * 2
    assert {e.actor for e in events} == {"system"}
    assert events[0].subject_type == "record"
    assert events[0].subject_id == first.record_id
    assert events[1].payload["version"] == 2
    assert events[1].payload["version_id"] == second.version_id
    assert events[1].payload["source_id"] == "wiki"
    assert "content" not in events[1].payload
    assert events[1].occurred_at == datetime(2026, 11, 14, 12, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"source_id": " "}, "record_invalid"),
        ({"external_id": ""}, "record_invalid"),
        ({"kind": ""}, "record_invalid"),
        ({"title": "   "}, "record_invalid"),
        ({"metadata": {"bad": object()}}, "record_invalid"),
        ({"content": "x" * 5000}, "record_too_large"),
    ],
)
def test_invalid_records_are_rejected_and_nothing_is_stored(
    ingestor: RecordIngestor, db: Database, overrides: dict[str, Any], code: str
) -> None:
    with pytest.raises(DomainError) as error:
        ingestor.ingest(make_record(**overrides))

    assert error.value.code == code
    assert count(db, RecordRow) == 0
    assert count(db, RecordVersionRow) == 0
    assert count(db, RecordVersionAclRow) == 0
    assert count(db, EventRow) == 0


def test_a_record_may_not_be_built_without_an_acl() -> None:
    with pytest.raises(DomainError) as error:
        make_record(acl=Acl(frozenset()))

    assert error.value.code == "acl_empty"


def test_content_is_stored_exactly_as_given_and_never_interpreted(
    ingestor: RecordIngestor, db: Database
) -> None:
    nasty = "'; DROP TABLE records; --<script>alert(1)</script> {{7*7}} $(rm -rf /)"

    result = ingestor.ingest(make_record(content=nasty))

    with db.transaction(write=False) as session:
        stored = session.get(RecordVersionRow, result.version_id)
    assert stored is not None
    assert stored.content == nasty
    assert count(db, RecordRow) == 1
