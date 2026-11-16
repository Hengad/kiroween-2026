"""The one exception type the API layer translates into problem-details responses."""


class DomainError(Exception):
    """A rule of the engine was violated.

    `code` is a stable machine-readable string. `status` is the HTTP status the
    API layer uses. `extra` carries additional problem-detail members.
    """

    def __init__(
        self,
        code: str,
        status: int,
        detail: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.status = status
        self.detail = detail
        self.extra: dict[str, object] = extra if extra is not None else {}


def not_found() -> DomainError:
    """The one error for a missing object and for an object the caller may not read.

    Both cases must look identical, so this is the only place the message lives."""
    return DomainError("not_found", 404, "Not found.")
