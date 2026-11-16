"""Access control lists."""

from dataclasses import dataclass

from siloless.access.principals import PrincipalId, ResolvedPrincipal, is_valid_principal_id
from siloless.errors import DomainError


@dataclass(frozen=True)
class Acl:
    """The principals allowed to read something. Never empty.

    `allows` is the single statement of the read rule. SQL read filters must
    agree with it, and property tests use it as the oracle.
    """

    principals: frozenset[PrincipalId]

    def __post_init__(self) -> None:
        if not self.principals:
            raise DomainError("acl_empty", 422, "An ACL must name at least one principal.")
        for entry in self.principals:
            if not is_valid_principal_id(entry):
                raise DomainError(
                    "record_invalid", 422, f"Malformed principal id in ACL: {entry!r}."
                )

    @classmethod
    def of(cls, *principals: PrincipalId) -> "Acl":
        return cls(frozenset(principals))

    def allows(self, who: ResolvedPrincipal) -> bool:
        return who.is_system or bool(self.principals & who.ids)
