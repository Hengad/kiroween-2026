from fastapi import APIRouter

from siloless.api.deps import ContainerDep
from siloless.api.schemas import MembershipsIn, MembershipsOut, PrincipalIn, PrincipalOut

router = APIRouter(tags=["principals"])


@router.put("/principals/{principal_id}")
def put_principal(principal_id: str, body: PrincipalIn, container: ContainerDep) -> PrincipalOut:
    """Create a user, group or role, or rename an existing one."""
    with container.db.transaction() as session:
        principal = container.directory.put(session, principal_id, body.name)
    return PrincipalOut.from_domain(principal)


@router.get("/principals")
def list_principals(container: ContainerDep) -> list[PrincipalOut]:
    with container.db.transaction(write=False) as session:
        return [PrincipalOut.from_domain(p) for p in container.directory.list(session)]


@router.put("/users/{user_id}/memberships")
def put_memberships(user_id: str, body: MembershipsIn, container: ContainerDep) -> MembershipsOut:
    """Replace the groups and roles a user belongs to."""
    with container.db.transaction() as session:
        container.directory.set_memberships(session, user_id, body.memberships)
    return MembershipsOut(user_id=user_id, memberships=sorted(set(body.memberships)))
