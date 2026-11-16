"""Work Items: creation, reading, claims, assignment, transitions and history.

Every state change is a single conditional UPDATE, so of several concurrent writers
exactly one matches the WHERE clause, and the Event Log entry is written in the same
transaction as the change it describes.
"""

from __future__ import annotations

import builtins
from typing import Any

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.orm import Session

from siloless.access.filters import record_version_readable, work_item_readable
from siloless.access.principals import PrincipalDirectory, ResolvedPrincipal
from siloless.clock import Clock
from siloless.errors import DomainError, not_found
from siloless.events.log import Event, EventLog
from siloless.ids import IdGenerator
from siloless.storage.db import Database
from siloless.storage.models import (
    RecordRow,
    RecordVersionRow,
    WorkItemEvidenceRow,
    WorkItemRow,
)
from siloless.work.domain import WORK_ITEM_KINDS, NewWorkItem, WorkItem
from siloless.work.lifecycle import check_transition

MAX_PAGE = 200


class WorkItemService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        events: EventLog,
        directory: PrincipalDirectory,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._events = events
        self._directory = directory

    # -- creating and reading ---------------------------------------------------

    def create(self, who: ResolvedPrincipal, new: NewWorkItem) -> WorkItem:
        self._validate(new)
        status = new.status or ("assigned" if new.owner else "open")
        evidence = tuple(dict.fromkeys(new.evidence))

        with self._db.transaction() as session:
            if new.owner is not None:
                self._directory.require_user(session, new.owner)
            for version_id in evidence:
                self._require_readable_version(session, who, version_id)

            now = self._clock.now()
            row = WorkItemRow(
                id=self._ids.new(),
                kind=new.kind,
                title=new.title.strip(),
                description=new.description,
                status=status,
                owner=new.owner,
                created_by=who.id,
                due_at=new.due_at,
                resolution=None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            session.add_all(
                WorkItemEvidenceRow(work_item_id=row.id, version_id=version_id, position=position)
                for position, version_id in enumerate(evidence)
            )
            self._events.append(
                session,
                type="work_item.created",
                actor=who.id,
                subject_type="work_item",
                subject_id=row.id,
                payload={
                    "changes": {
                        "kind": row.kind,
                        "title": row.title,
                        "description": row.description,
                        "status": row.status,
                        "owner": row.owner,
                        "resolution": None,
                        "due_at": new.due_at.isoformat() if new.due_at else None,
                        "created_by": who.id,
                        "evidence": list(evidence),
                    }
                },
            )
            return self._item(session, who, row)

    def get(self, who: ResolvedPrincipal, item_id: str) -> WorkItem:
        with self._db.transaction(write=False) as session:
            return self._item(session, who, self._readable_row(session, who, item_id))

    def list(
        self,
        who: ResolvedPrincipal,
        *,
        kind: str | None = None,
        status: str | None = None,
        owner: str | None = None,
        before: str | None = None,
        limit: int = 50,
    ) -> builtins.list[WorkItem]:
        """Readable items, newest first. ULIDs sort by creation time, so `before` (the id
        of the last item on the previous page) is a stable cursor."""
        query = select(WorkItemRow).where(work_item_readable(who))
        if kind is not None:
            query = query.where(WorkItemRow.kind == kind)
        if status is not None:
            query = query.where(WorkItemRow.status == status)
        if owner is not None:
            query = query.where(WorkItemRow.owner == owner)
        if before is not None:
            query = query.where(WorkItemRow.id < before)
        query = query.order_by(WorkItemRow.id.desc()).limit(max(1, min(limit, MAX_PAGE)))
        with self._db.transaction(write=False) as session:
            return [self._item(session, who, row) for row in session.execute(query).scalars()]

    def history(self, who: ResolvedPrincipal, item_id: str) -> builtins.list[Event]:
        """The item's events, oldest first."""
        with self._db.transaction(write=False) as session:
            self._readable_row(session, who, item_id)
            return self._events.for_subject(session, who, "work_item", item_id)

    # -- changing ---------------------------------------------------------------

    def claim(self, who: ResolvedPrincipal, item_id: str) -> WorkItem:
        """Mark an open, unowned item as being investigated by `who`. One claim wins."""
        self._require_user_actor(who)
        with self._db.transaction() as session:
            self._readable_row(session, who, item_id)
            result = session.execute(
                update(WorkItemRow)
                .where(
                    WorkItemRow.id == item_id,
                    WorkItemRow.owner.is_(None),
                    WorkItemRow.status == "open",
                )
                .values(owner=who.id, status="investigating", updated_at=self._clock.now())
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                owner, status = session.execute(
                    select(WorkItemRow.owner, WorkItemRow.status).where(WorkItemRow.id == item_id)
                ).one()
                if owner is not None:
                    raise DomainError(
                        "already_owned", 409, f"Already being handled by {owner}.", {"owner": owner}
                    )
                raise DomainError(
                    "invalid_transition",
                    409,
                    f"Only open items can be claimed; this one is {status}.",
                )
            self._record(
                session,
                who,
                item_id,
                "work_item.claimed",
                {"owner": who.id, "status": "investigating"},
                {"owner": None, "status": "open"},
            )
            return self._item(session, who, self._fresh_row(session, item_id))

    def assign(self, who: ResolvedPrincipal, item_id: str, new_owner: str) -> WorkItem:
        """Give the item to another user, whatever its current owner."""
        with self._db.transaction() as session:
            row = self._readable_row(session, who, item_id)
            self._directory.require_user(session, new_owner)
            old_status, old_owner = row.status, row.owner
            if old_status in ("awaiting_acceptance", "resolved"):
                raise DomainError(
                    "not_assignable", 409, f"An item that is {old_status} cannot be assigned."
                )
            new_status = "assigned" if old_status in ("open", "reopened") else old_status
            if new_status != old_status:
                check_transition(old_status, new_status)
            if old_owner == new_owner and new_status == old_status:
                return self._item(session, who, row)

            values: dict[str, Any] = {"owner": new_owner, "updated_at": self._clock.now()}
            changes: dict[str, Any] = {"owner": new_owner}
            if new_status != old_status:
                values["status"] = new_status
                changes["status"] = new_status
            self._update_if_unchanged(session, item_id, old_status, old_owner, values)
            self._record(
                session,
                who,
                item_id,
                "work_item.assigned",
                changes,
                {"owner": old_owner, "status": old_status},
            )
            return self._item(session, who, self._fresh_row(session, item_id))

    def transition(
        self,
        who: ResolvedPrincipal,
        item_id: str,
        to: str,
        resolution: str | None = None,
    ) -> WorkItem:
        """Move the item along the lifecycle.

        Claiming and assigning have their own methods, because they involve an owner."""
        with self._db.transaction() as session:
            row = self._readable_row(session, who, item_id)
            old_status, old_owner, old_resolution = row.status, row.owner, row.resolution
            if to == "assigned":
                raise DomainError(
                    "invalid_transition", 409, "Use assign to give an item to someone."
                )
            if old_status == "open" and to == "investigating":
                raise DomainError("invalid_transition", 409, "Use claim to take an open item.")
            check_transition(old_status, to)

            values: dict[str, Any] = {"status": to, "updated_at": self._clock.now()}
            changes: dict[str, Any] = {"status": to}
            if to == "resolved":
                if resolution is None or not resolution.strip():
                    raise DomainError(
                        "resolution_required", 422, "Resolving an item needs a resolution text."
                    )
                values["resolution"] = changes["resolution"] = resolution
            elif to == "reopened":
                values["resolution"] = changes["resolution"] = None
            if to == "investigating" and old_owner is None:
                self._require_user_actor(who)
                values["owner"] = changes["owner"] = who.id

            self._update_if_unchanged(session, item_id, old_status, old_owner, values)
            self._record(
                session,
                who,
                item_id,
                "work_item.status_changed",
                changes,
                {"status": old_status, "owner": old_owner, "resolution": old_resolution},
            )
            return self._item(session, who, self._fresh_row(session, item_id))

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _validate(new: NewWorkItem) -> None:
        if new.kind not in WORK_ITEM_KINDS:
            raise DomainError("work_item_invalid", 422, f"Unknown work item kind: {new.kind!r}.")
        if not new.title.strip():
            raise DomainError("work_item_invalid", 422, "A work item needs a title.")
        if new.status is not None and new.status not in ("open", "awaiting_acceptance"):
            raise DomainError(
                "work_item_invalid",
                422,
                "A new work item can only start open or awaiting_acceptance.",
            )
        if new.due_at is not None and new.due_at.tzinfo is None:
            raise DomainError("work_item_invalid", 422, "The due date must include a time zone.")
        if new.owner is not None and new.status is not None:
            raise DomainError(
                "work_item_invalid",
                422,
                "A work item with an owner starts assigned; omit the status.",
            )

    @staticmethod
    def _require_user_actor(who: ResolvedPrincipal) -> None:
        if who.is_system:
            raise DomainError(
                "owner_must_be_user", 422, "The system principal cannot own work items."
            )

    @staticmethod
    def _require_readable_version(
        session: Session, who: ResolvedPrincipal, version_id: str
    ) -> None:
        found = session.execute(
            select(RecordVersionRow.id)
            .join(RecordRow, RecordRow.id == RecordVersionRow.record_id)
            .where(RecordVersionRow.id == version_id, record_version_readable(who))
        ).first()
        if found is None:
            raise DomainError("node_not_found", 422, f"No record version with id {version_id!r}.")

    @staticmethod
    def _readable_row(session: Session, who: ResolvedPrincipal, item_id: str) -> WorkItemRow:
        row = (
            session.execute(
                select(WorkItemRow)
                .where(WorkItemRow.id == item_id, work_item_readable(who))
                .execution_options(populate_existing=True)
            )
            .scalars()
            .first()
        )
        if row is None:
            raise not_found()
        return row

    @staticmethod
    def _fresh_row(session: Session, item_id: str) -> WorkItemRow:
        return session.execute(
            select(WorkItemRow)
            .where(WorkItemRow.id == item_id)
            .execution_options(populate_existing=True)
        ).scalar_one()

    @staticmethod
    def _update_if_unchanged(
        session: Session,
        item_id: str,
        status: str,
        owner: str | None,
        values: dict[str, Any],
    ) -> None:
        """Apply `values` only if the item still has the status and owner we read."""
        owner_matches: ColumnElement[bool] = (
            WorkItemRow.owner.is_(None) if owner is None else WorkItemRow.owner == owner
        )
        result = session.execute(
            update(WorkItemRow)
            .where(WorkItemRow.id == item_id, WorkItemRow.status == status, owner_matches)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            raise DomainError(
                "concurrent_modification", 409, "The item changed while it was being updated."
            )

    def _record(
        self,
        session: Session,
        who: ResolvedPrincipal,
        item_id: str,
        type_: str,
        changes: dict[str, Any],
        before: dict[str, Any],
    ) -> None:
        self._events.append(
            session,
            type=type_,
            actor=who.id,
            subject_type="work_item",
            subject_id=item_id,
            payload={"changes": changes, "before": before},
        )

    @staticmethod
    def _item(session: Session, who: ResolvedPrincipal, row: WorkItemRow) -> WorkItem:
        evidence = session.execute(
            select(WorkItemEvidenceRow.version_id)
            .join(RecordVersionRow, RecordVersionRow.id == WorkItemEvidenceRow.version_id)
            .join(RecordRow, RecordRow.id == RecordVersionRow.record_id)
            .where(WorkItemEvidenceRow.work_item_id == row.id, record_version_readable(who))
            .order_by(WorkItemEvidenceRow.position)
        ).scalars()
        return WorkItem(
            id=row.id,
            kind=row.kind,
            title=row.title,
            description=row.description,
            status=row.status,
            owner=row.owner,
            created_by=row.created_by,
            due_at=row.due_at,
            resolution=row.resolution,
            created_at=row.created_at,
            updated_at=row.updated_at,
            evidence=tuple(evidence),
        )


def can_read_work_item(session: Session, who: ResolvedPrincipal, item_id: str) -> bool:
    query = select(WorkItemRow.id).where(WorkItemRow.id == item_id, work_item_readable(who))
    return session.execute(query).first() is not None
