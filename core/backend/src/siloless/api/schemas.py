"""Request and response models. Mapping to and from domain objects happens here."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from siloless.access.principals import Principal
from siloless.events.log import Event
from siloless.memory.domain import (
    Entity,
    EntityDetail,
    IngestResult,
    NodeRef,
    RecordVersion,
    Relation,
)
from siloless.memory.search import SearchHit
from siloless.work.domain import WorkItem


class PrincipalIn(BaseModel):
    name: str


class PrincipalOut(BaseModel):
    id: str
    type: str
    name: str

    @classmethod
    def from_domain(cls, principal: Principal) -> "PrincipalOut":
        return cls(id=principal.id, type=principal.type, name=principal.name)


class MembershipsIn(BaseModel):
    memberships: list[str]


class MembershipsOut(BaseModel):
    user_id: str
    memberships: list[str]


class RecordIn(BaseModel):
    source_id: str
    external_id: str
    kind: str
    title: str
    content: str
    metadata: dict[str, Any] = {}
    acl: list[str]
    occurred_at: datetime


class IngestOut(BaseModel):
    record_id: str
    version_id: str
    version: int
    created: bool

    @classmethod
    def from_domain(cls, result: IngestResult) -> "IngestOut":
        return cls(
            record_id=result.record_id,
            version_id=result.version_id,
            version=result.version,
            created=result.created,
        )


class RecordVersionOut(BaseModel):
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
    is_authoritative: bool

    @classmethod
    def from_domain(cls, version: RecordVersion) -> "RecordVersionOut":
        return cls(**vars(version))


class SearchHitOut(BaseModel):
    record_id: str
    version_id: str
    version: int
    title: str
    passage: str
    source_id: str
    kind: str
    is_authoritative: bool

    @classmethod
    def from_domain(cls, hit: SearchHit) -> "SearchHitOut":
        return cls(**vars(hit))


# -- entities and relations ---------------------------------------------------------


class EntityIn(BaseModel):
    entity_type: str
    key: str
    name: str
    attributes: dict[str, Any] = {}


class EntityOut(BaseModel):
    id: str
    entity_type: str
    key: str
    name: str
    attributes: dict[str, Any]

    @classmethod
    def from_domain(cls, entity: Entity) -> "EntityOut":
        return cls(**vars(entity))


class EntityIngestOut(EntityOut):
    created: bool


class EntityDetailOut(BaseModel):
    entity: EntityOut
    records: list[RecordVersionOut]

    @classmethod
    def from_domain(cls, detail: EntityDetail) -> "EntityDetailOut":
        return cls(
            entity=EntityOut.from_domain(detail.entity),
            records=[RecordVersionOut.from_domain(v) for v in detail.records],
        )


class NodeModel(BaseModel):
    kind: Literal["record_version", "entity"]
    id: str

    @classmethod
    def from_domain(cls, node: NodeRef) -> "NodeModel":
        return cls(kind=node.kind, id=node.id)

    def to_domain(self) -> NodeRef:
        return NodeRef(self.kind, self.id)


class RelationIn(BaseModel):
    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    relation_type: str
    from_node: NodeModel = Field(alias="from")
    to_node: NodeModel = Field(alias="to")


def _relation_fields(relation: Relation) -> dict[str, Any]:
    return {
        "id": relation.id,
        "relation_type": relation.relation_type,
        "from_node": NodeModel.from_domain(relation.from_node),
        "to_node": NodeModel.from_domain(relation.to_node),
    }


class RelationOut(BaseModel):
    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True)

    id: str
    relation_type: str
    from_node: NodeModel = Field(alias="from")
    to_node: NodeModel = Field(alias="to")

    @classmethod
    def from_domain(cls, relation: Relation) -> "RelationOut":
        return cls.model_validate(_relation_fields(relation))


class RelationIngestOut(RelationOut):
    created: bool

    @classmethod
    def of(cls, relation: Relation, created: bool) -> "RelationIngestOut":
        return cls.model_validate({**_relation_fields(relation), "created": created})


# -- work items and events ----------------------------------------------------------


class WorkItemIn(BaseModel):
    kind: str
    title: str
    description: str = ""
    due_at: datetime | None = None
    evidence: list[str] = []
    owner: str | None = None
    status: str | None = None


class WorkItemOut(BaseModel):
    id: str
    kind: str
    title: str
    description: str
    status: str
    owner: str | None
    created_by: str
    due_at: datetime | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime
    evidence: list[str]

    @classmethod
    def from_domain(cls, item: WorkItem) -> "WorkItemOut":
        return cls(**{**vars(item), "evidence": list(item.evidence)})


class AssignIn(BaseModel):
    owner: str


class TransitionIn(BaseModel):
    to: str
    resolution: str | None = None


class EventOut(BaseModel):
    seq: int
    id: str
    occurred_at: datetime
    type: str
    actor: str
    subject_type: str
    subject_id: str
    payload: dict[str, Any]

    @classmethod
    def from_domain(cls, event: Event) -> "EventOut":
        return cls(**vars(event))


class ProblemDetails(BaseModel):
    """The body of every error response (RFC 9457 problem details).

    `code` is a stable, machine-readable string such as `not_found` or `already_owned`.
    Some errors add members, for example `owner` on `already_owned`."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str
