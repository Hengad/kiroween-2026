from fastapi import APIRouter, Response

from siloless.access.acl import Acl
from siloless.api.deps import ContainerDep
from siloless.api.schemas import (
    EntityIn,
    EntityIngestOut,
    IngestOut,
    RecordIn,
    RelationIn,
    RelationIngestOut,
)
from siloless.memory.domain import NewRecord

router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("/records", responses={200: {"model": IngestOut}, 201: {"model": IngestOut}})
def ingest_record(body: RecordIn, response: Response, container: ContainerDep) -> IngestOut:
    """Push one item from a Source. Idempotent: an unchanged item is acknowledged with 200,
    a new item or a changed item creates a version and returns 201."""
    result = container.ingestor.ingest(
        NewRecord(
            source_id=body.source_id,
            external_id=body.external_id,
            kind=body.kind,
            title=body.title,
            content=body.content,
            metadata=body.metadata,
            acl=Acl(frozenset(body.acl)),
            occurred_at=body.occurred_at,
        )
    )
    response.status_code = 201 if result.created else 200
    return IngestOut.from_domain(result)


@router.post(
    "/entities", responses={200: {"model": EntityIngestOut}, 201: {"model": EntityIngestOut}}
)
def ingest_entity(body: EntityIn, response: Response, container: ContainerDep) -> EntityIngestOut:
    """Create an Entity, or update its name and attributes if one with the same type and key
    exists. 201 when created, 200 otherwise."""
    result = container.entities.upsert(body.entity_type, body.key, body.name, body.attributes)
    response.status_code = 201 if result.created else 200
    return EntityIngestOut(**vars(result.entity), created=result.created)


@router.post(
    "/relations", responses={200: {"model": RelationIngestOut}, 201: {"model": RelationIngestOut}}
)
def ingest_relation(
    body: RelationIn, response: Response, container: ContainerDep
) -> RelationIngestOut:
    """Link two nodes (a Record version or an Entity). An identical Relation is returned
    as it is with 200; a new one returns 201."""
    result = container.relations.create(
        body.relation_type, body.from_node.to_domain(), body.to_node.to_domain()
    )
    response.status_code = 201 if result.created else 200
    return RelationIngestOut.of(result.relation, result.created)
