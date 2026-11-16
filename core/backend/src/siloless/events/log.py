"""The append-only Event Log.

`append` is the only write path and `for_subject` the only read path. There is no
update or delete. Events are written in the caller's transaction, so an event exists
exactly when the change it describes does.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from siloless.access.principals import PrincipalId, ResolvedPrincipal
from siloless.clock import Clock
from siloless.ids import IdGenerator
from siloless.storage.models import EventRow

# Decides whether `who` may read the subject with this id.
SubjectCheck = Callable[[Session, ResolvedPrincipal, str], bool]

MAX_PAGE = 1000


@dataclass(frozen=True)
class Event:
    seq: int
    id: str
    occurred_at: datetime
    type: str
    actor: PrincipalId
    subject_type: str
    subject_id: str
    payload: dict[str, Any]


class EventLog:
    """Each module registers a readability check for the subjects it owns, so the
    log does not depend on memory or work. A subject type with no check is denied."""

    def __init__(self, clock: Clock, ids: IdGenerator) -> None:
        self._clock = clock
        self._ids = ids
        self._checks: dict[str, SubjectCheck] = {}

    def register_subject_check(self, subject_type: str, check: SubjectCheck) -> None:
        self._checks[subject_type] = check

    def append(
        self,
        session: Session,
        *,
        type: str,
        actor: PrincipalId,
        subject_type: str,
        subject_id: str,
        payload: dict[str, Any],
    ) -> Event:
        row = EventRow(
            id=self._ids.new(),
            occurred_at=self._clock.now(),
            type=type,
            actor=actor,
            subject_type=subject_type,
            subject_id=subject_id,
            payload=payload,
        )
        session.add(row)
        session.flush()
        return _to_event(row)

    def for_subject(
        self,
        session: Session,
        who: ResolvedPrincipal,
        subject_type: str,
        subject_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> list[Event]:
        """Events for one subject, oldest first. Empty if `who` may not read the subject,
        which looks the same as a subject that does not exist."""
        check = self._checks.get(subject_type)
        if check is None or not (who.is_system or check(session, who, subject_id)):
            return []
        query = (
            select(EventRow)
            .where(
                EventRow.subject_type == subject_type,
                EventRow.subject_id == subject_id,
                EventRow.seq > after_seq,
            )
            .order_by(EventRow.seq)
            .limit(max(1, min(limit, MAX_PAGE)))
        )
        return [_to_event(row) for row in session.execute(query).scalars()]


def _to_event(row: EventRow) -> Event:
    return Event(
        seq=row.seq,
        id=row.id,
        occurred_at=row.occurred_at,
        type=row.type,
        actor=row.actor,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        payload=row.payload,
    )
