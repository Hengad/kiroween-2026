"""Memory domain objects (frozen, no storage or HTTP concerns)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from siloless.access.acl import Acl
from siloless.clock import ensure_utc
from siloless.errors import DomainError


@dataclass(frozen=True)
class NewRecord:
    """One item pushed from a Source, before it is stored.

    A Source names an item with (`source_id`, `external_id`). Pushing the same item
    again with changed content creates a new version of the same Record.
    """

    source_id: str
    external_id: str
    kind: str
    title: str
    content: str
    metadata: dict[str, Any]
    acl: Acl
    occurred_at: datetime

    def __post_init__(self) -> None:
        for name in ("source_id", "external_id", "kind", "title"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise DomainError("record_invalid", 422, f"Record field '{name}' is required.")
        if not isinstance(self.content, str):
            raise DomainError("record_invalid", 422, "Record field 'content' must be text.")
        try:
            ensure_utc(self.occurred_at)
        except ValueError as error:
            raise DomainError(
                "record_invalid", 422, "Record field 'occurred_at' must include a time zone."
            ) from error


@dataclass(frozen=True)
class RecordVersion:
    """One stored version of a Record, as returned to a reader."""

    record_id: str
    version_id: str
    version: int
    source_id: str
    external_id: str
    kind: str
    title: str
    content: str
    metadata: dict[str, Any]
    occurred_at: datetime
    ingested_at: datetime
    is_current: bool
    """True for the newest version. Older versions are superseded."""
    is_authoritative: bool


@dataclass(frozen=True)
class IngestResult:
    record_id: str
    version_id: str
    version: int
    created: bool
    """True when a new version was stored, false when the item was already up to date."""


NodeKind = Literal["record_version", "entity"]


@dataclass(frozen=True)
class NodeRef:
    """One end of a Relation: a specific Record version, or an Entity."""

    kind: NodeKind
    id: str


@dataclass(frozen=True)
class Entity:
    id: str
    entity_type: str
    key: str
    name: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class Relation:
    id: str
    relation_type: str
    from_node: NodeRef
    to_node: NodeRef


@dataclass(frozen=True)
class EntityResult:
    entity: Entity
    created: bool


@dataclass(frozen=True)
class RelationResult:
    relation: Relation
    created: bool


@dataclass(frozen=True)
class EntityDetail:
    """An Entity and the Record versions linked to it that the reader may read."""

    entity: Entity
    records: list[RecordVersion]
