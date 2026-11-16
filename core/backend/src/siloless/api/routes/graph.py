from typing import Literal

from fastapi import APIRouter

from siloless.api.deps import ContainerDep, PrincipalDep
from siloless.api.schemas import EntityDetailOut, RelationOut
from siloless.memory.domain import NodeRef

router = APIRouter(tags=["graph"])


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str, who: PrincipalDep, container: ContainerDep) -> EntityDetailOut:
    """An Entity and the linked Record versions you may read."""
    return EntityDetailOut.from_domain(container.entities.get(who, entity_id))


@router.get("/nodes/{node_type}/{node_id}/relations")
def get_node_relations(
    node_type: Literal["record_version", "entity"],
    node_id: str,
    who: PrincipalDep,
    container: ContainerDep,
) -> list[RelationOut]:
    """Relations that touch a node, from either end, that you may read."""
    relations = container.relations.for_node(who, NodeRef(node_type, node_id))
    return [RelationOut.from_domain(relation) for relation in relations]
