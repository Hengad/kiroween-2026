from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from siloless.api.deps import ContainerDep, PrincipalDep
from siloless.api.schemas import SearchHitOut
from siloless.memory.search import SearchQuery

router = APIRouter(tags=["search"])


@router.get("/search")
def search(
    who: PrincipalDep,
    container: ContainerDep,
    q: str,
    source: str | None = None,
    kind: str | None = None,
    occurred_from: Annotated[datetime | None, Query(alias="from")] = None,
    occurred_to: Annotated[datetime | None, Query(alias="to")] = None,
    entity: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SearchHitOut]:
    """Full-text search over the current version of every Record you may read."""
    hits = container.search.search(
        who,
        SearchQuery(
            text=q,
            source_id=source,
            kind=kind,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            entity_id=entity,
            limit=limit,
        ),
    )
    return [SearchHitOut.from_domain(hit) for hit in hits]
