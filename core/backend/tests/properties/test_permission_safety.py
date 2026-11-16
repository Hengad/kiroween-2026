"""Permission safety: nothing is ever returned to a Principal who may not read it,
and nothing readable is ever withheld."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from siloless.access.acl import Acl
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord, NodeRef
from siloless.storage.db import Database
from tests.helpers import Services, build_services
from tests.strategies import EVERYONE, USERS, IngestOp, ingest_ops, memberships

PROPERTY_SETTINGS = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@dataclass
class ModelRecord:
    """What the world should look like, kept independently of the engine."""

    record_id: str
    versions: list[tuple[str, frozenset[str]]] = field(default_factory=list)  # oldest first


def apply_ops(svc: Services, ops: list[IngestOp]) -> dict[str, ModelRecord]:
    model: dict[str, ModelRecord] = {}
    for op in ops:
        result = svc.ingestor.ingest(
            NewRecord(
                source_id="s",
                external_id=op.key,
                kind="doc",
                title=f"Title {op.key}",
                content=f"text variant {op.variant}",
                metadata={},
                acl=Acl(op.acl),
                occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        record = model.setdefault(op.key, ModelRecord(result.record_id))
        if result.created:
            record.versions.append((result.version_id, op.acl))
    return model


def oracle_readable(record: ModelRecord, user_ids: frozenset[str]) -> list[str]:
    """Version ids the user may read, newest first. Independent of Acl.allows."""
    current_acl = record.versions[-1][1]
    if not (current_acl & user_ids):
        return []
    return [vid for vid, acl in reversed(record.versions) if acl & user_ids]


def error_of(call: Callable[..., Any], *args: Any) -> tuple[str, int, str]:
    try:
        call(*args)
    except DomainError as error:
        return (error.code, error.status, error.detail)
    raise AssertionError("expected a DomainError")


def new_world(
    member_map: dict[str, frozenset[str]], ops: list[IngestOp]
) -> tuple[Services, dict[str, Any], dict[str, ModelRecord]]:
    database = Database.in_memory()
    database.create_schema()
    svc = build_services(database, entity_types=["thing"])
    users = {user: svc.add_user(user, member_map[user]) for user in USERS}
    return svc, users, apply_ops(svc, ops)


@PROPERTY_SETTINGS
@given(member_map=memberships(), ops=st.lists(ingest_ops, min_size=1, max_size=10))
def test_reads_return_exactly_what_the_oracle_says_each_user_may_read(
    member_map: dict[str, frozenset[str]], ops: list[IngestOp]
) -> None:
    svc, users, model = new_world(member_map, ops)
    try:
        for user, who in users.items():
            assert who.ids == frozenset({user, EVERYONE, *member_map[user]})

            for record in model.values():
                expected = oracle_readable(record, who.ids)
                current_id = record.versions[-1][0]

                # list_versions: exactly the readable versions, newest first.
                if expected:
                    listed = svc.reader.list_versions(who, record.record_id)
                    assert [v.version_id for v in listed] == expected
                    assert [v.is_current for v in listed] == [vid == current_id for vid in expected]
                else:
                    code = error_of(svc.reader.list_versions, who, record.record_id)[0]
                    assert code == "not_found"

                # get_current: succeeds exactly when the current version is readable.
                if current_id in expected:
                    assert svc.reader.get_current(who, record.record_id).version_id == current_id
                else:
                    assert error_of(svc.reader.get_current, who, record.record_id)[0] == "not_found"

                # get_version, for every version of the record.
                for version_id, _ in record.versions:
                    if version_id in expected:
                        assert svc.reader.get_version(who, version_id).version_id == version_id
                    else:
                        assert error_of(svc.reader.get_version, who, version_id)[0] == "not_found"
    finally:
        svc.db.dispose()


@PROPERTY_SETTINGS
@given(member_map=memberships(), ops=st.lists(ingest_ops, min_size=1, max_size=10))
def test_an_unreadable_record_is_indistinguishable_from_a_missing_one(
    member_map: dict[str, frozenset[str]], ops: list[IngestOp]
) -> None:
    svc, users, model = new_world(member_map, ops)
    try:
        for who in users.values():
            for record in model.values():
                if oracle_readable(record, who.ids):
                    continue
                version_id = record.versions[-1][0]
                for call, hidden, missing in [
                    (svc.reader.get_current, record.record_id, "missing"),
                    (svc.reader.get_version, version_id, "missing"),
                    (svc.reader.list_versions, record.record_id, "missing"),
                ]:
                    assert error_of(call, who, hidden) == error_of(call, who, missing)
    finally:
        svc.db.dispose()


@PROPERTY_SETTINGS
@given(member_map=memberships(), ops=st.lists(ingest_ops, min_size=1, max_size=10))
def test_search_returns_exactly_the_readable_current_records(
    member_map: dict[str, frozenset[str]], ops: list[IngestOp]
) -> None:
    from siloless.memory.search import SearchQuery

    svc, users, model = new_world(member_map, ops)
    try:
        for who in users.values():
            # Every generated record contains the word "text", so all of them match.
            expected = {
                record.versions[-1][0]
                for record in model.values()
                if record.versions[-1][0] in oracle_readable(record, who.ids)
            }

            hits = svc.search.search(who, SearchQuery("text", limit=100))

            assert {hit.version_id for hit in hits} == expected
            assert len(hits) == len(expected)
    finally:
        svc.db.dispose()


@PROPERTY_SETTINGS
@given(member_map=memberships(), ops=st.lists(ingest_ops, min_size=1, max_size=10))
def test_relations_entity_links_and_their_events_follow_record_readability(
    member_map: dict[str, frozenset[str]], ops: list[IngestOp]
) -> None:
    svc, users, model = new_world(member_map, ops)
    try:
        entity_id = svc.entities.upsert("thing", "t", "T", {}).entity.id
        entity = NodeRef("entity", entity_id)

        # Link EVERY version of every record, old ones included, to the entity.
        linked: dict[str, tuple[ModelRecord, str]] = {}
        for record in model.values():
            for version_id, _ in record.versions:
                relation = svc.relations.create(
                    "about", NodeRef("record_version", version_id), entity
                ).relation
                linked[relation.id] = (record, version_id)

        for who in users.values():
            readable = {
                relation_id
                for relation_id, (record, version_id) in linked.items()
                if version_id in oracle_readable(record, who.ids)
            }

            assert {r.id for r in svc.relations.for_node(who, entity)} == readable

            detail = svc.entities.get(who, entity_id)
            assert {v.version_id for v in detail.records} == {linked[r][1] for r in readable}

            with svc.db.transaction(write=False) as session:
                for relation_id in linked:
                    events = svc.events.for_subject(session, who, "relation", relation_id)
                    assert bool(events) == (relation_id in readable)
    finally:
        svc.db.dispose()
