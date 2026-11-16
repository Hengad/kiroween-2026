"""Entities and Relations: the memory graph."""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from siloless.access.filters import record_version_readable, relation_readable
from siloless.access.principals import SYSTEM, ResolvedPrincipal
from siloless.errors import DomainError, not_found
from siloless.events.log import EventLog
from siloless.ids import IdGenerator
from siloless.memory.domain import (
    Entity,
    EntityDetail,
    EntityResult,
    NodeRef,
    Relation,
    RelationResult,
)
from siloless.memory.records import to_record_version
from siloless.settings import Settings
from siloless.storage.db import Database
from siloless.storage.models import EntityRow, RecordRow, RecordVersionRow, RelationRow


class SchemaRegistry:
    """The Entity types and Relation types an application has registered."""

    def __init__(self, entity_types: Iterable[str], relation_types: Iterable[str]) -> None:
        self._entity_types = frozenset(entity_types)
        self._relation_types = frozenset(relation_types)

    def check_entity_type(self, name: str) -> None:
        if name not in self._entity_types:
            raise DomainError(
                "unknown_entity_type", 422, f"Entity type {name!r} is not registered."
            )

    def check_relation_type(self, name: str) -> None:
        if name not in self._relation_types:
            raise DomainError(
                "unknown_relation_type", 422, f"Relation type {name!r} is not registered."
            )


def _to_entity(row: EntityRow) -> Entity:
    return Entity(row.id, row.entity_type, row.key, row.name, row.attributes)


class EntityStore:
    """Entities are identified by (type, key), so a connector can submit them repeatedly."""

    def __init__(
        self,
        db: Database,
        ids: IdGenerator,
        events: EventLog,
        registry: SchemaRegistry,
        settings: Settings,
    ) -> None:
        self._db = db
        self._ids = ids
        self._events = events
        self._registry = registry
        self._settings = settings

    def upsert(
        self, entity_type: str, key: str, name: str, attributes: dict[str, Any]
    ) -> EntityResult:
        """Create the Entity, or update its name and attributes if they changed.

        An unchanged resubmission stores nothing and appends no event."""
        self._registry.check_entity_type(entity_type)
        if not key.strip() or not name.strip():
            raise DomainError("entity_invalid", 422, "An entity needs a key and a name.")

        with self._db.transaction() as session:
            row = session.execute(
                select(EntityRow).where(EntityRow.entity_type == entity_type, EntityRow.key == key)
            ).scalar_one_or_none()

            if row is None:
                row = EntityRow(
                    id=self._ids.new(),
                    entity_type=entity_type,
                    key=key,
                    name=name,
                    attributes=attributes,
                )
                session.add(row)
                session.flush()
                self._append(
                    session,
                    "entity.created",
                    row.id,
                    {
                        "entity_type": entity_type,
                        "key": key,
                        "name": name,
                    },
                )
                return EntityResult(_to_entity(row), created=True)

            changes: dict[str, Any] = {}
            if row.name != name:
                changes["name"] = name
            if row.attributes != attributes:
                changes["attributes"] = attributes
            if changes:
                row.name = name
                row.attributes = attributes
                self._append(session, "entity.updated", row.id, {"changes": changes})
            return EntityResult(_to_entity(row), created=False)

    def get(self, who: ResolvedPrincipal, entity_id: str) -> EntityDetail:
        """An Entity, plus the linked Record versions the reader may read. Linked
        Records the reader may not read are omitted without any trace."""
        with self._db.transaction(write=False) as session:
            row = session.get(EntityRow, entity_id)
            if row is None:
                raise not_found()
            linked_from = select(RelationRow.to_version_id).where(
                RelationRow.from_entity_id == entity_id, RelationRow.to_version_id.is_not(None)
            )
            linked_to = select(RelationRow.from_version_id).where(
                RelationRow.to_entity_id == entity_id, RelationRow.from_version_id.is_not(None)
            )
            found = session.execute(
                select(RecordVersionRow, RecordRow)
                .join(RecordRow, RecordRow.id == RecordVersionRow.record_id)
                .where(
                    or_(RecordVersionRow.id.in_(linked_from), RecordVersionRow.id.in_(linked_to)),
                    record_version_readable(who),
                )
                .order_by(RecordVersionRow.id)
            ).all()
            return EntityDetail(
                _to_entity(row),
                [to_record_version(v, r, self._settings) for v, r in found],
            )

    def _append(
        self, session: Session, type_: str, entity_id: str, payload: dict[str, Any]
    ) -> None:
        self._events.append(
            session,
            type=type_,
            actor=SYSTEM,
            subject_type="entity",
            subject_id=entity_id,
            payload=payload,
        )


def _columns(prefix: str, node: NodeRef) -> dict[str, str | None]:
    return {
        f"{prefix}_version_id": node.id if node.kind == "record_version" else None,
        f"{prefix}_entity_id": node.id if node.kind == "entity" else None,
    }


def _node(version_id: str | None, entity_id: str | None) -> NodeRef:
    if version_id is not None:
        return NodeRef("record_version", version_id)
    assert entity_id is not None  # a CHECK constraint guarantees exactly one is set
    return NodeRef("entity", entity_id)


def _to_relation(row: RelationRow) -> Relation:
    return Relation(
        id=row.id,
        relation_type=row.relation_type,
        from_node=_node(row.from_version_id, row.from_entity_id),
        to_node=_node(row.to_version_id, row.to_entity_id),
    )


class RelationStore:
    def __init__(
        self, db: Database, ids: IdGenerator, events: EventLog, registry: SchemaRegistry
    ) -> None:
        self._db = db
        self._ids = ids
        self._events = events
        self._registry = registry

    def create(self, relation_type: str, from_node: NodeRef, to_node: NodeRef) -> RelationResult:
        """Link two nodes. An identical Relation that already exists is returned as is."""
        self._registry.check_relation_type(relation_type)
        with self._db.transaction() as session:
            self._require_exists(session, from_node)
            self._require_exists(session, to_node)

            columns = {**_columns("from", from_node), **_columns("to", to_node)}
            same = [
                getattr(RelationRow, name).is_(None)
                if value is None
                else getattr(RelationRow, name) == value
                for name, value in columns.items()
            ]
            existing = session.execute(
                select(RelationRow).where(RelationRow.relation_type == relation_type, *same)
            ).scalar_one_or_none()
            if existing is not None:
                return RelationResult(_to_relation(existing), created=False)

            row = RelationRow(id=self._ids.new(), relation_type=relation_type, **columns)
            session.add(row)
            session.flush()
            self._events.append(
                session,
                type="relation.created",
                actor=SYSTEM,
                subject_type="relation",
                subject_id=row.id,
                payload={
                    "relation_type": relation_type,
                    "from": {"kind": from_node.kind, "id": from_node.id},
                    "to": {"kind": to_node.kind, "id": to_node.id},
                },
            )
            return RelationResult(_to_relation(row), created=True)

    def for_node(self, who: ResolvedPrincipal, node: NodeRef) -> list[Relation]:
        """Relations that touch the node, from either end, that the reader may read."""
        if node.kind == "record_version":
            touches = or_(
                RelationRow.from_version_id == node.id, RelationRow.to_version_id == node.id
            )
        else:
            touches = and_(
                or_(RelationRow.from_entity_id == node.id, RelationRow.to_entity_id == node.id)
            )
        with self._db.transaction(write=False) as session:
            rows = session.execute(
                select(RelationRow).where(touches, relation_readable(who)).order_by(RelationRow.id)
            ).scalars()
            return [_to_relation(row) for row in rows]

    @staticmethod
    def _require_exists(session: Session, node: NodeRef) -> None:
        model = RecordVersionRow if node.kind == "record_version" else EntityRow
        if session.get(model, node.id) is None:
            raise DomainError("node_not_found", 422, f"No {node.kind} with id {node.id!r}.")


def can_read_entity(session: Session, _who: ResolvedPrincipal, entity_id: str) -> bool:
    """Entities are readable by every known principal."""
    return session.get(EntityRow, entity_id) is not None


def can_read_relation(session: Session, who: ResolvedPrincipal, relation_id: str) -> bool:
    query = select(RelationRow.id).where(RelationRow.id == relation_id, relation_readable(who))
    return session.execute(query).first() is not None
