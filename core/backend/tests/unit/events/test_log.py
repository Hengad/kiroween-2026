from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from siloless.access.principals import ResolvedPrincipal
from siloless.clock import ManualClock
from siloless.events.log import EventLog
from siloless.ids import UlidGenerator
from siloless.storage.db import Database

ANNA = ResolvedPrincipal.for_user("user:anna", [])


def allow_all(_session: Session, _who: ResolvedPrincipal, _subject_id: str) -> bool:
    return True


@pytest.fixture
def log(clock: ManualClock, ids: UlidGenerator) -> EventLog:
    event_log = EventLog(clock, ids)
    event_log.register_subject_check("record", allow_all)
    return event_log


def _append(
    log: EventLog, db: Database, subject_id: str = "r1", type_: str = "record.changed"
) -> int:
    with db.transaction() as session:
        event = log.append(
            session,
            type=type_,
            actor="system",
            subject_type="record",
            subject_id=subject_id,
            payload={"n": 1},
        )
        return event.seq


def _read(
    log: EventLog, db: Database, subject_id: str = "r1", **kwargs: int
) -> list[tuple[int, str]]:
    with db.transaction(write=False) as session:
        events = log.for_subject(session, ANNA, "record", subject_id, **kwargs)
        return [(e.seq, e.type) for e in events]


def test_append_stamps_the_injected_time_and_a_sortable_id(
    log: EventLog, db: Database, clock: ManualClock
) -> None:
    with db.transaction() as session:
        event = log.append(
            session,
            type="record.version_added",
            actor="user:anna",
            subject_type="record",
            subject_id="r1",
            payload={"version": 1},
        )

    assert event.occurred_at == datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert len(event.id) == 26
    assert event.actor == "user:anna"
    assert event.payload == {"version": 1}


def test_sequence_numbers_only_grow(log: EventLog, db: Database) -> None:
    seqs = [_append(log, db) for _ in range(5)]

    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 5


def test_events_for_a_subject_come_back_in_append_order_and_only_for_that_subject(
    log: EventLog, db: Database, clock: ManualClock
) -> None:
    _append(log, db, "r1", "first")
    clock.advance(timedelta(seconds=1))
    _append(log, db, "r2", "other")
    _append(log, db, "r1", "second")
    _append(log, db, "r1", "third")

    types = [type_ for _, type_ in _read(log, db, "r1")]

    assert types == ["first", "second", "third"]


def test_after_seq_and_limit_page_through_the_events(log: EventLog, db: Database) -> None:
    for _ in range(6):
        _append(log, db)
    everything = _read(log, db)

    first_page = _read(log, db, limit=2)
    second_page = _read(log, db, after_seq=first_page[-1][0], limit=2)

    assert first_page == everything[:2]
    assert second_page == everything[2:4]


def test_an_event_in_a_rolled_back_transaction_does_not_exist(log: EventLog, db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction() as session:
        log.append(
            session,
            type="record.changed",
            actor="system",
            subject_type="record",
            subject_id="r1",
            payload={},
        )
        raise RuntimeError("boom")

    assert _read(log, db) == []


def test_the_log_offers_no_way_to_update_or_delete_events() -> None:
    public = {name for name in dir(EventLog) if not name.startswith("_")}

    assert not {name for name in public if name.startswith(("update", "delete", "remove"))}


def test_events_of_an_unreadable_subject_look_the_same_as_events_of_a_missing_one(
    clock: ManualClock, ids: UlidGenerator, db: Database
) -> None:
    log = EventLog(clock, ids)
    log.register_subject_check("record", lambda _s, _w, subject_id: subject_id == "visible")
    _append(log, db, "visible")
    _append(log, db, "hidden")

    assert len(_read(log, db, "visible")) == 1
    assert _read(log, db, "hidden") == []
    assert _read(log, db, "never-existed") == []


def test_a_subject_type_without_a_readability_check_is_denied(
    clock: ManualClock, ids: UlidGenerator, db: Database
) -> None:
    log = EventLog(clock, ids)
    with db.transaction() as session:
        log.append(
            session,
            type="x",
            actor="system",
            subject_type="mystery",
            subject_id="m1",
            payload={},
        )

    with db.transaction(write=False) as session:
        assert log.for_subject(session, ANNA, "mystery", "m1") == []
