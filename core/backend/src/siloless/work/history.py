"""Rebuilding a Work Item's state from its events. Pure."""

from collections.abc import Iterable

from siloless.events.log import Event
from siloless.work.domain import WorkItemState


def replay(events: Iterable[Event]) -> WorkItemState:
    """Fold the `changes` of each event, oldest first, into the current state.

    Every Work Item event records the fields it changed, so the log alone is enough
    to say what the item looks like now. The first event must be the creation."""
    fields: dict[str, object] = {}
    seen_creation = False
    for event in events:
        if not seen_creation:
            if event.type != "work_item.created":
                raise ValueError("a work item's history must start with its creation event")
            seen_creation = True
        fields.update(event.payload["changes"])
    if not seen_creation:
        raise ValueError("a work item's history must start with its creation event")

    evidence = fields.get("evidence", [])
    if not isinstance(evidence, list | tuple):
        raise ValueError("evidence must be a list of version ids")

    return WorkItemState(
        kind=str(fields["kind"]),
        title=str(fields["title"]),
        description=str(fields["description"]),
        status=str(fields["status"]),
        owner=_optional(fields.get("owner")),
        resolution=_optional(fields.get("resolution")),
        due_at=_optional(fields.get("due_at")),
        created_by=str(fields["created_by"]),
        evidence=tuple(str(item) for item in evidence),
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)
