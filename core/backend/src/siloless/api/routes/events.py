from typing import Annotated

from fastapi import APIRouter, Query

from siloless.api.deps import ContainerDep, PrincipalDep
from siloless.api.schemas import EventOut

router = APIRouter(tags=["events"])


@router.get("/events")
def list_events(
    who: PrincipalDep,
    container: ContainerDep,
    subject_type: str,
    subject_id: str,
    after_seq: int = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[EventOut]:
    """The Event Log entries for one subject (a record, entity, relation or work item),
    oldest first. A subject you may not read looks the same as one that does not exist:
    an empty list."""
    with container.db.transaction(write=False) as session:
        events = container.events.for_subject(
            session, who, subject_type, subject_id, after_seq=after_seq, limit=limit
        )
    return [EventOut.from_domain(event) for event in events]
