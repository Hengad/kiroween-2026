"""Relations only ever connect nodes that exist."""

from datetime import UTC, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from siloless.access.acl import Acl
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord, NodeRef
from siloless.storage.models import EntityRow, RecordVersionRow, RelationRow
from tests.helpers import build_services

node_choice = st.tuples(st.sampled_from(["record_version", "entity"]), st.integers(0, 3))
relation_ops = st.lists(st.tuples(node_choice, node_choice), min_size=1, max_size=15)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=relation_ops)
def test_a_relation_is_stored_exactly_when_both_endpoints_exist(
    ops: list[tuple[tuple[str, int], tuple[str, int]]],
) -> None:
    svc = build_services(entity_types=["machine"])
    try:
        versions = [
            svc.ingestor.ingest(
                NewRecord(
                    source_id="s",
                    external_id=f"r{index}",
                    kind="doc",
                    title="t",
                    content="c",
                    metadata={},
                    acl=Acl.of("group:everyone"),
                    occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
                )
            ).version_id
            for index in range(2)
        ]
        entities = [
            svc.entities.upsert("machine", f"m{i}", f"M{i}", {}).entity.id for i in range(2)
        ]
        pools = {"record_version": versions, "entity": entities}

        def pick(choice: tuple[str, int]) -> tuple[NodeRef, bool]:
            kind, index = choice
            pool = pools[kind]
            if index < len(pool):
                return NodeRef(kind, pool[index]), True  # type: ignore[arg-type]
            return NodeRef(kind, f"missing-{index}"), False  # type: ignore[arg-type]

        for from_choice, to_choice in ops:
            from_node, from_exists = pick(from_choice)
            to_node, to_exists = pick(to_choice)
            try:
                svc.relations.create("about", from_node, to_node)
                stored = True
            except DomainError as error:
                assert error.code == "node_not_found"
                stored = False
            assert stored == (from_exists and to_exists)

        # Whatever happened, every stored relation points at nodes that exist.
        with svc.db.transaction(write=False) as session:
            relations = session.execute(select(RelationRow)).scalars().all()
            version_ids = set(session.execute(select(RecordVersionRow.id)).scalars())
            entity_ids = set(session.execute(select(EntityRow.id)).scalars())
        for relation in relations:
            for version_id, entity_id in [
                (relation.from_version_id, relation.from_entity_id),
                (relation.to_version_id, relation.to_entity_id),
            ]:
                assert (version_id is None) != (entity_id is None)
                assert version_id in version_ids or entity_id in entity_ids
    finally:
        svc.db.dispose()
