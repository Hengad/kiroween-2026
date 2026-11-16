"""Principals: the identities a request is made on behalf of."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from siloless.errors import DomainError
from siloless.storage.models import MembershipRow, PrincipalRow

PrincipalId = str

SYSTEM: PrincipalId = "system"
EVERYONE: PrincipalId = "group:everyone"

_PRINCIPAL_ID = re.compile(r"^(user|group|role):[a-z0-9][a-z0-9._-]*$")


def is_valid_principal_id(value: str) -> bool:
    """True for `user:anna`, `group:maintenance` or `role:shift-lead` style ids."""
    return _PRINCIPAL_ID.fullmatch(value) is not None


@dataclass(frozen=True)
class ResolvedPrincipal:
    """A principal with its memberships expanded, ready to filter reads.

    `id` is the acting identity (a user, or SYSTEM). `ids` is that identity plus
    every group and role it belongs to, plus the built-in `group:everyone`. A
    Record is readable when its ACL shares an entry with `ids`.
    """

    id: PrincipalId
    ids: frozenset[PrincipalId]
    is_system: bool = False

    @classmethod
    def for_user(
        cls, user_id: PrincipalId, memberships: Iterable[PrincipalId]
    ) -> "ResolvedPrincipal":
        return cls(id=user_id, ids=frozenset({user_id, *memberships, EVERYONE}))

    @classmethod
    def system(cls) -> "ResolvedPrincipal":
        return cls(id=SYSTEM, ids=frozenset({SYSTEM}), is_system=True)


@dataclass(frozen=True)
class Principal:
    id: PrincipalId
    type: str
    name: str


class PrincipalDirectory:
    """Stores principals and memberships, and resolves a user to a ResolvedPrincipal.

    Stateless: every method takes the caller's Session, so it joins the caller's
    transaction. Nothing is cached, so membership changes apply to the next read.
    """

    def put(self, session: Session, principal_id: PrincipalId, name: str) -> Principal:
        """Create a principal, or rename an existing one."""
        if not is_valid_principal_id(principal_id):
            raise DomainError(
                "principal_invalid", 422, f"Malformed principal id: {principal_id!r}."
            )
        kind = principal_id.split(":", 1)[0]
        row = session.get(PrincipalRow, principal_id)
        if row is None:
            session.add(PrincipalRow(id=principal_id, type=kind, name=name))
        else:
            row.name = name
        return Principal(principal_id, kind, name)

    def list(self, session: Session) -> list[Principal]:
        rows = session.execute(select(PrincipalRow).order_by(PrincipalRow.id)).scalars()
        return [Principal(row.id, row.type, row.name) for row in rows]

    def set_memberships(
        self, session: Session, user_id: PrincipalId, targets: Iterable[PrincipalId]
    ) -> None:
        """Replace the groups and roles a user belongs to."""
        user = self._existing(session, user_id, status=422)
        if user.type != "user":
            raise DomainError("principal_invalid", 422, "Only users can have memberships.")
        wanted = set(targets)
        for target_id in wanted:
            if not is_valid_principal_id(target_id):
                raise DomainError(
                    "principal_invalid", 422, f"Malformed principal id: {target_id!r}."
                )
            target = self._existing(session, target_id, status=422)
            if target.type not in ("group", "role"):
                raise DomainError(
                    "principal_invalid", 422, "Memberships must name a group or a role."
                )
        session.execute(delete(MembershipRow).where(MembershipRow.user_id == user_id))
        session.add_all(MembershipRow(user_id=user_id, target_id=target_id) for target_id in wanted)

    def resolve(self, session: Session, principal_id: PrincipalId) -> ResolvedPrincipal:
        """Expand a user to everything it belongs to. Only stored users can be resolved."""
        row = (
            session.get(PrincipalRow, principal_id) if is_valid_principal_id(principal_id) else None
        )
        if row is None or row.type != "user":
            raise DomainError("principal_unknown", 403, "Unknown principal.")
        targets = session.execute(
            select(MembershipRow.target_id).where(MembershipRow.user_id == principal_id)
        ).scalars()
        return ResolvedPrincipal.for_user(principal_id, targets)

    def require_user(self, session: Session, principal_id: PrincipalId) -> None:
        """Check that a Work Item owner exists and is a user, not a group or role."""
        row = (
            session.get(PrincipalRow, principal_id) if is_valid_principal_id(principal_id) else None
        )
        if row is None:
            raise DomainError("owner_unknown", 422, f"Unknown user: {principal_id!r}.")
        if row.type != "user":
            raise DomainError("owner_must_be_user", 422, "Only users can own work items.")

    @staticmethod
    def _existing(session: Session, principal_id: PrincipalId, *, status: int) -> PrincipalRow:
        row = (
            session.get(PrincipalRow, principal_id) if is_valid_principal_id(principal_id) else None
        )
        if row is None:
            raise DomainError("principal_unknown", status, f"Unknown principal: {principal_id!r}.")
        return row
