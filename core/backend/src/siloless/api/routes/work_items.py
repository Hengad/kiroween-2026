from typing import Annotated

from fastapi import APIRouter, Query

from siloless.api.deps import ContainerDep, PrincipalDep
from siloless.api.schemas import AssignIn, EventOut, TransitionIn, WorkItemIn, WorkItemOut
from siloless.work.domain import NewWorkItem

router = APIRouter(prefix="/work-items", tags=["work items"])


@router.post("", status_code=201)
def create_work_item(body: WorkItemIn, who: PrincipalDep, container: ContainerDep) -> WorkItemOut:
    """Create a question, request, incident or action."""
    item = container.items.create(
        who,
        NewWorkItem(
            kind=body.kind,
            title=body.title,
            description=body.description,
            due_at=body.due_at,
            evidence=tuple(body.evidence),
            owner=body.owner,
            status=body.status,
        ),
    )
    return WorkItemOut.from_domain(item)


@router.get("")
def list_work_items(
    who: PrincipalDep,
    container: ContainerDep,
    kind: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    before: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[WorkItemOut]:
    """Items you may read, newest first. Page with `before` set to the last id you saw."""
    items = container.items.list(
        who, kind=kind, status=status, owner=owner, before=before, limit=limit
    )
    return [WorkItemOut.from_domain(item) for item in items]


@router.get("/{item_id}")
def get_work_item(item_id: str, who: PrincipalDep, container: ContainerDep) -> WorkItemOut:
    return WorkItemOut.from_domain(container.items.get(who, item_id))


@router.post("/{item_id}/claim")
def claim_work_item(item_id: str, who: PrincipalDep, container: ContainerDep) -> WorkItemOut:
    """Mark an open item as "investigating" so nobody else duplicates the work. If someone
    got there first the response is 409 with the owner's id."""
    return WorkItemOut.from_domain(container.items.claim(who, item_id))


@router.post("/{item_id}/assign")
def assign_work_item(
    item_id: str, body: AssignIn, who: PrincipalDep, container: ContainerDep
) -> WorkItemOut:
    return WorkItemOut.from_domain(container.items.assign(who, item_id, body.owner))


@router.post("/{item_id}/transition")
def transition_work_item(
    item_id: str, body: TransitionIn, who: PrincipalDep, container: ContainerDep
) -> WorkItemOut:
    """Move an item along its lifecycle. Resolving needs a `resolution` text."""
    return WorkItemOut.from_domain(
        container.items.transition(who, item_id, body.to, body.resolution)
    )


@router.get("/{item_id}/history")
def work_item_history(item_id: str, who: PrincipalDep, container: ContainerDep) -> list[EventOut]:
    """Everything that happened to the item, oldest first."""
    return [EventOut.from_domain(event) for event in container.items.history(who, item_id)]
