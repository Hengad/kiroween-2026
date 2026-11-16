"""Request dependencies: the service container and the requesting Principal."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader

from siloless.access.principals import SYSTEM, ResolvedPrincipal
from siloless.container import Container
from siloless.errors import DomainError

PRINCIPAL_HEADER = "X-Principal-Id"

# Declared as a security scheme so the API docs offer an Authorize button for it.
_principal_header = APIKeyHeader(
    name=PRINCIPAL_HEADER,
    auto_error=False,
    description=(
        "Who is asking, for example `user:anna`. There is no authentication in this "
        "version: the header is trusted."
    ),
)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_principal(
    container: ContainerDep, value: Annotated[str | None, Depends(_principal_header)]
) -> ResolvedPrincipal:
    """Identify the caller from the principal header.

    There is no authentication in this version: the header is trusted. It is the
    only place that trust is placed, and the system principal can never be named."""
    if not value:
        raise DomainError("principal_required", 400, f"The {PRINCIPAL_HEADER} header is required.")
    if value == SYSTEM:
        raise DomainError("principal_forbidden", 403, "The system principal cannot be used.")
    with container.db.transaction(write=False) as session:
        return container.directory.resolve(session, value)


PrincipalDep = Annotated[ResolvedPrincipal, Depends(get_principal)]
