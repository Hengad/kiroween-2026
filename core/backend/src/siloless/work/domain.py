"""Work Item domain objects."""

from dataclasses import dataclass
from datetime import datetime

WORK_ITEM_KINDS: tuple[str, ...] = ("question", "request", "incident", "action")


@dataclass(frozen=True)
class WorkItemState:
    """The current state of a Work Item, as rebuilt from its events or read from storage."""

    kind: str
    title: str
    description: str
    status: str
    owner: str | None
    resolution: str | None
    due_at: str | None
    created_by: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class NewWorkItem:
    """What a caller supplies to create a Work Item.

    `status` may be left out (the item starts `open`, or `assigned` when an owner is
    given) or set to `awaiting_acceptance`. An owner and a status cannot be combined."""

    kind: str
    title: str
    description: str = ""
    due_at: datetime | None = None
    evidence: tuple[str, ...] = ()
    owner: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class WorkItem:
    """A Work Item as returned to a reader. `evidence` lists only Record versions the
    reader may read."""

    id: str
    kind: str
    title: str
    description: str
    status: str
    owner: str | None
    created_by: str
    due_at: datetime | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime
    evidence: tuple[str, ...]
