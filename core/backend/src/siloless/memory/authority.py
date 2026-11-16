"""Authoritative Records: the official answer, as opposed to a casual message."""

from collections.abc import Collection


def is_authoritative(
    *,
    source_id: str,
    kind: str,
    is_current: bool,
    authoritative_sources: Collection[str],
    authoritative_kinds: Collection[str],
) -> bool:
    """A version is authoritative only if it is the current version and its Source or
    kind is configured as authoritative. With nothing configured, nothing is.

    Evaluated when a Record is read, so a newer version removes authority from the
    older one without any extra bookkeeping."""
    if not is_current:
        return False
    return source_id in authoritative_sources or kind in authoritative_kinds
