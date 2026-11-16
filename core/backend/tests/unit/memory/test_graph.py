from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select

from siloless.access.acl import Acl
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord, NodeRef
from siloless.memory.search import SearchQuery
from siloless.storage.models import EntityRow, EventRow, RelationRow
from tests.helpers import Services, build_services


@pytest.fixture
def svc() -> Services:
    return build_services(entity_types=["machine", "person"], relation_types=["feeds"])


def make_record(**overrides: Any) -> NewRecord:
    base = NewRecord(
        source_id="wiki",
        external_id="doc",
        kind="procedure",
        title="Seal replacement",
        content="Replace the hydraulic seal.",
        metadata={},
        acl=Acl.of("group:maintenance"),
        occurred_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
    )
    return replace(base, **overrides)


def count(svc: Services, model: type) -> int:
    with svc.db.transaction(write=False) as session:
        return session.execute(select(func.count()).select_from(model)).scalar_one()


def event_types(svc: Services) -> list[str]:
    with svc.db.transaction(write=False) as session:
        return list(session.execute(select(EventRow.type).order_by(EventRow.seq)).scalars())


def error_code(call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(DomainError) as error:
        call(*args, **kwargs)
    return error.value.code


def press(svc: Services) -> str:
    return svc.entities.upsert("machine", "press-3", "Press 3", {"line": 1}).entity.id


def version_ref(version_id: str) -> NodeRef:
    return NodeRef("record_version", version_id)


def entity_ref(entity_id: str) -> NodeRef:
    return NodeRef("entity", entity_id)


# -- type registry ------------------------------------------------------------------


def test_an_unregistered_entity_type_is_rejected(svc: Services) -> None:
    assert error_code(svc.entities.upsert, "spaceship", "x", "X", {}) == "unknown_entity_type"
    assert count(svc, EntityRow) == 0


def test_an_unregistered_relation_type_is_rejected(svc: Services) -> None:
    a = svc.entities.upsert("machine", "a", "A", {}).entity.id
    b = svc.entities.upsert("machine", "b", "B", {}).entity.id

    assert (
        error_code(svc.relations.create, "teleports_to", entity_ref(a), entity_ref(b))
        == "unknown_relation_type"
    )


def test_builtin_and_configured_relation_types_are_accepted(svc: Services) -> None:
    a = svc.entities.upsert("machine", "a", "A", {}).entity.id
    b = svc.entities.upsert("machine", "b", "B", {}).entity.id

    svc.relations.create("located_at", entity_ref(a), entity_ref(b))
    svc.relations.create("feeds", entity_ref(a), entity_ref(b))

    assert count(svc, RelationRow) == 2


# -- entities -----------------------------------------------------------------------


def test_a_new_entity_is_created_with_an_id(svc: Services) -> None:
    result = svc.entities.upsert("machine", "press-3", "Press 3", {"line": 1})

    assert result.created
    assert len(result.entity.id) == 26
    assert result.entity.entity_type == "machine"
    assert result.entity.key == "press-3"
    assert result.entity.attributes == {"line": 1}
    assert event_types(svc) == ["entity.created"]


def test_submitting_an_unchanged_entity_again_changes_nothing(svc: Services) -> None:
    first = svc.entities.upsert("machine", "press-3", "Press 3", {"line": 1})

    again = svc.entities.upsert("machine", "press-3", "Press 3", {"line": 1})

    assert not again.created
    assert again.entity.id == first.entity.id
    assert event_types(svc) == ["entity.created"]


def test_a_changed_entity_is_updated_in_place_with_an_event(svc: Services) -> None:
    first = svc.entities.upsert("machine", "press-3", "Press 3", {"line": 1})

    updated = svc.entities.upsert("machine", "press-3", "Press 3 (new)", {"line": 2})

    assert not updated.created
    assert updated.entity.id == first.entity.id
    assert updated.entity.name == "Press 3 (new)"
    assert updated.entity.attributes == {"line": 2}
    assert event_types(svc) == ["entity.created", "entity.updated"]
    assert count(svc, EntityRow) == 1


def test_the_same_key_under_another_type_is_a_different_entity(svc: Services) -> None:
    a = svc.entities.upsert("machine", "x1", "A", {}).entity.id
    b = svc.entities.upsert("person", "x1", "B", {}).entity.id

    assert a != b


# -- relations ----------------------------------------------------------------------


def test_a_relation_links_a_record_version_to_an_entity(svc: Services) -> None:
    record = svc.ingestor.ingest(make_record())
    entity_id = press(svc)

    result = svc.relations.create("about", version_ref(record.version_id), entity_ref(entity_id))

    assert result.created
    assert result.relation.relation_type == "about"
    assert result.relation.from_node == version_ref(record.version_id)
    assert result.relation.to_node == entity_ref(entity_id)
    assert event_types(svc)[-1] == "relation.created"


def test_an_identical_relation_is_not_stored_twice(svc: Services) -> None:
    record = svc.ingestor.ingest(make_record())
    entity_id = press(svc)
    first = svc.relations.create("about", version_ref(record.version_id), entity_ref(entity_id))
    events_before = len(event_types(svc))

    again = svc.relations.create("about", version_ref(record.version_id), entity_ref(entity_id))

    assert not again.created
    assert again.relation.id == first.relation.id
    assert count(svc, RelationRow) == 1
    assert len(event_types(svc)) == events_before


def test_a_relation_to_a_missing_node_is_rejected_and_stores_nothing(svc: Services) -> None:
    record = svc.ingestor.ingest(make_record())
    entity_id = press(svc)

    for from_node, to_node in [
        (version_ref("missing"), entity_ref(entity_id)),
        (version_ref(record.version_id), entity_ref("missing")),
        (entity_ref("missing"), entity_ref(entity_id)),
    ]:
        assert error_code(svc.relations.create, "about", from_node, to_node) == "node_not_found"

    assert count(svc, RelationRow) == 0


def test_a_record_id_is_not_a_valid_relation_endpoint(svc: Services) -> None:
    record = svc.ingestor.ingest(make_record())
    entity_id = press(svc)

    # Relations attach to a version, never to the logical record.
    code = error_code(
        svc.relations.create, "about", version_ref(record.record_id), entity_ref(entity_id)
    )

    assert code == "node_not_found"


def test_a_relation_between_entities_is_visible_to_everyone(svc: Services) -> None:
    anyone = svc.add_user("user:anyone")
    a = svc.entities.upsert("machine", "a", "A", {}).entity.id
    b = svc.entities.upsert("machine", "b", "B", {}).entity.id
    svc.relations.create("located_at", entity_ref(a), entity_ref(b))

    assert len(svc.relations.for_node(anyone, entity_ref(a))) == 1
    assert len(svc.relations.for_node(anyone, entity_ref(b))) == 1


def test_a_relation_with_a_record_is_visible_only_to_people_who_can_read_it(
    svc: Services,
) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    bo = svc.add_user("user:bo", ["group:sales"])
    record = svc.ingestor.ingest(make_record())
    entity_id = press(svc)
    svc.relations.create("about", version_ref(record.version_id), entity_ref(entity_id))

    assert len(svc.relations.for_node(anna, entity_ref(entity_id))) == 1
    assert len(svc.relations.for_node(anna, version_ref(record.version_id))) == 1
    assert svc.relations.for_node(bo, entity_ref(entity_id)) == []
    assert svc.relations.for_node(bo, version_ref(record.version_id)) == []


def test_relations_are_found_from_either_end(svc: Services) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    record = svc.ingestor.ingest(make_record())
    entity_id = press(svc)
    svc.relations.create("mentions", entity_ref(entity_id), version_ref(record.version_id))

    from_entity = svc.relations.for_node(anna, entity_ref(entity_id))
    from_version = svc.relations.for_node(anna, version_ref(record.version_id))

    assert [r.id for r in from_entity] == [r.id for r in from_version]


def test_losing_access_to_a_record_hides_relations_built_on_its_old_versions(
    svc: Services,
) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    first = svc.ingestor.ingest(make_record(acl=Acl.of("group:maintenance")))
    entity_id = press(svc)
    svc.relations.create("about", version_ref(first.version_id), entity_ref(entity_id))
    assert len(svc.relations.for_node(anna, entity_ref(entity_id))) == 1

    svc.ingestor.ingest(make_record(acl=Acl.of("group:management")))

    assert svc.relations.for_node(anna, entity_ref(entity_id)) == []


# -- reading an entity --------------------------------------------------------------


def test_reading_an_entity_lists_only_the_linked_records_the_reader_may_read(
    svc: Services,
) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    bo = svc.add_user("user:bo", ["group:sales"])
    secret = svc.ingestor.ingest(make_record(external_id="secret", acl=Acl.of("group:maintenance")))
    public = svc.ingestor.ingest(make_record(external_id="public", acl=Acl.of("group:everyone")))
    entity_id = press(svc)
    svc.relations.create("about", version_ref(secret.version_id), entity_ref(entity_id))
    svc.relations.create("about", version_ref(public.version_id), entity_ref(entity_id))

    for_anna = svc.entities.get(anna, entity_id)
    for_bo = svc.entities.get(bo, entity_id)

    assert for_anna.entity.name == "Press 3"
    assert {v.version_id for v in for_anna.records} == {secret.version_id, public.version_id}
    assert [v.version_id for v in for_bo.records] == [public.version_id]


def test_reading_a_missing_entity_is_not_found(svc: Services) -> None:
    anna = svc.add_user("user:anna")

    assert error_code(svc.entities.get, anna, "missing") == "not_found"


# -- search by entity ---------------------------------------------------------------


def test_search_can_be_restricted_to_records_linked_to_an_entity(svc: Services) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    linked = svc.ingestor.ingest(make_record(external_id="a", title="Seal A"))
    svc.ingestor.ingest(make_record(external_id="b", title="Seal B"))
    entity_id = press(svc)
    svc.relations.create("about", version_ref(linked.version_id), entity_ref(entity_id))

    hits = svc.search.search(anna, SearchQuery("seal", entity_id=entity_id))
    everything = svc.search.search(anna, SearchQuery("seal"))

    assert [h.title for h in hits] == ["Seal A"]
    assert len(everything) == 2


# -- events -------------------------------------------------------------------------


def test_events_for_relations_follow_the_relation_visibility(svc: Services) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    bo = svc.add_user("user:bo", ["group:sales"])
    record = svc.ingestor.ingest(make_record())
    entity_id = press(svc)
    relation = svc.relations.create("about", version_ref(record.version_id), entity_ref(entity_id))

    with svc.db.transaction(write=False) as session:
        for_anna = svc.events.for_subject(session, anna, "relation", relation.relation.id)
        for_bo = svc.events.for_subject(session, bo, "relation", relation.relation.id)
        entity_events = svc.events.for_subject(session, bo, "entity", entity_id)

    assert [e.type for e in for_anna] == ["relation.created"]
    assert for_bo == []
    assert [e.type for e in entity_events] == ["entity.created"]
