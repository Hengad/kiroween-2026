from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from siloless.access.acl import Acl
from siloless.access.principals import ResolvedPrincipal
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord
from tests.helpers import Services, build_services


@pytest.fixture
def svc() -> Services:
    return build_services(authoritative_sources=["wiki"])


def make_record(**overrides: Any) -> NewRecord:
    base = NewRecord(
        source_id="wiki",
        external_id="press-3-seal",
        kind="procedure",
        title="Press 3 seal replacement",
        content="Replace the hydraulic seal every 500 hours.",
        metadata={},
        acl=Acl.of("group:maintenance"),
        occurred_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
    )
    return replace(base, **overrides)


def error_of(call: Any) -> tuple[str, int, str]:
    with pytest.raises(DomainError) as error:
        call()
    return (error.value.code, error.value.status, error.value.detail)


def test_a_reader_gets_the_current_version_of_a_record(svc: Services) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    svc.ingestor.ingest(make_record())
    second = svc.ingestor.ingest(make_record(content="Replace the seal every 400 hours."))

    version = svc.reader.get_current(anna, second.record_id)

    assert version.version_id == second.version_id
    assert version.version == 2
    assert version.content == "Replace the seal every 400 hours."
    assert version.is_current
    assert version.source_id == "wiki"
    assert version.record_id == second.record_id


def test_the_current_version_of_an_authoritative_source_is_marked_authoritative(
    svc: Services,
) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    wiki = svc.ingestor.ingest(make_record())
    chat = svc.ingestor.ingest(make_record(source_id="chat", external_id="m1"))

    assert svc.reader.get_current(anna, wiki.record_id).is_authoritative
    assert not svc.reader.get_current(anna, chat.record_id).is_authoritative


def test_versions_come_back_newest_first_with_only_the_latest_marked_current(
    svc: Services,
) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    first = svc.ingestor.ingest(make_record())
    svc.ingestor.ingest(make_record(content="Every 400 hours."))
    third = svc.ingestor.ingest(make_record(content="Every 300 hours."))

    versions = svc.reader.list_versions(anna, first.record_id)

    assert [v.version for v in versions] == [3, 2, 1]
    assert [v.is_current for v in versions] == [True, False, False]
    assert versions[0].version_id == third.version_id
    assert [v.is_authoritative for v in versions] == [True, False, False]
    assert versions[2].content == "Replace the hydraulic seal every 500 hours."


def test_a_single_version_can_be_read_by_its_id(svc: Services) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    first = svc.ingestor.ingest(make_record())
    svc.ingestor.ingest(make_record(content="Every 400 hours."))

    old = svc.reader.get_version(anna, first.version_id)

    assert old.version == 1
    assert not old.is_current


def test_an_unreadable_record_looks_exactly_like_a_missing_one(svc: Services) -> None:
    bo = svc.add_user("user:bo", ["group:sales"])
    hidden = svc.ingestor.ingest(make_record())

    for call_hidden, call_missing in [
        (
            lambda: svc.reader.get_current(bo, hidden.record_id),
            lambda: svc.reader.get_current(bo, "nope"),
        ),
        (
            lambda: svc.reader.get_version(bo, hidden.version_id),
            lambda: svc.reader.get_version(bo, "nope"),
        ),
        (
            lambda: svc.reader.list_versions(bo, hidden.record_id),
            lambda: svc.reader.list_versions(bo, "nope"),
        ),
    ]:
        assert error_of(call_hidden) == error_of(call_missing)
        assert error_of(call_hidden)[0] == "not_found"
        assert error_of(call_hidden)[1] == 404


def test_tightening_access_hides_every_older_version_from_people_who_lost_it(
    svc: Services,
) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    bo = svc.add_user("user:bo", ["group:management"])
    first = svc.ingestor.ingest(make_record(acl=Acl.of("group:maintenance")))
    second = svc.ingestor.ingest(make_record(acl=Acl.of("group:management")))

    # Anna lost access in version 2, so she loses the old version she used to read.
    assert error_of(lambda: svc.reader.get_current(anna, first.record_id))[0] == "not_found"
    assert error_of(lambda: svc.reader.get_version(anna, first.version_id))[0] == "not_found"
    assert error_of(lambda: svc.reader.list_versions(anna, first.record_id))[0] == "not_found"

    # Bo can read the current version but never could read version 1.
    assert svc.reader.get_current(bo, first.record_id).version_id == second.version_id
    assert [v.version for v in svc.reader.list_versions(bo, first.record_id)] == [2]
    assert error_of(lambda: svc.reader.get_version(bo, first.version_id))[0] == "not_found"


def test_widening_access_does_not_expose_older_versions_to_the_new_readers(
    svc: Services,
) -> None:
    both = svc.add_user("user:cy", ["group:maintenance", "group:management"])
    new_only = svc.add_user("user:di", ["group:management"])
    first = svc.ingestor.ingest(make_record(acl=Acl.of("group:maintenance")))
    svc.ingestor.ingest(make_record(acl=Acl.of("group:maintenance", "group:management")))

    assert [v.version for v in svc.reader.list_versions(both, first.record_id)] == [2, 1]
    assert [v.version for v in svc.reader.list_versions(new_only, first.record_id)] == [2]


def test_the_system_principal_reads_everything(svc: Services) -> None:
    first = svc.ingestor.ingest(make_record(acl=Acl.of("group:maintenance")))
    svc.ingestor.ingest(make_record(acl=Acl.of("group:management")))
    system = ResolvedPrincipal.system()

    assert [v.version for v in svc.reader.list_versions(system, first.record_id)] == [2, 1]


def test_events_of_a_record_are_visible_only_to_people_who_can_read_it(svc: Services) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    bo = svc.add_user("user:bo", ["group:sales"])
    result = svc.ingestor.ingest(make_record())

    with svc.db.transaction(write=False) as session:
        for_anna = svc.events.for_subject(session, anna, "record", result.record_id)
        for_bo = svc.events.for_subject(session, bo, "record", result.record_id)

    assert [e.type for e in for_anna] == ["record.version_added"]
    assert for_bo == []
