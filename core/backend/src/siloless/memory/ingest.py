"""Ingesting Records: idempotent, versioned, one transaction per item."""

import hashlib
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from siloless.access.principals import SYSTEM
from siloless.clock import Clock
from siloless.errors import DomainError
from siloless.events.log import EventLog
from siloless.ids import IdGenerator
from siloless.memory.domain import IngestResult, NewRecord
from siloless.settings import Settings
from siloless.storage.db import Database
from siloless.storage.models import (
    RecordRow,
    RecordVersionAclRow,
    RecordVersionRow,
)


class RecordIngestor:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        ids: IdGenerator,
        events: EventLog,
        settings: Settings,
    ) -> None:
        self._db = db
        self._clock = clock
        self._ids = ids
        self._events = events
        self._settings = settings

    def ingest(self, new: NewRecord) -> IngestResult:
        """Store a Record item.

        New item: version 1. Same item, same content: nothing changes. Same item,
        changed title, content, metadata, kind or ACL: a new version, with earlier
        versions left untouched. `occurred_at` alone is not a change.
        """
        content_hash = self._hash_and_check_size(new)

        with self._db.transaction() as session:
            record = session.execute(
                select(RecordRow).where(
                    RecordRow.source_id == new.source_id,
                    RecordRow.external_id == new.external_id,
                )
            ).scalar_one_or_none()

            if record is None:
                record = RecordRow(
                    id=self._ids.new(),
                    source_id=new.source_id,
                    external_id=new.external_id,
                    current_version_id=None,
                )
                session.add(record)
                version_number = 1
            else:
                current = session.get(RecordVersionRow, record.current_version_id)
                assert current is not None  # a Record always has a current version
                if current.content_hash == content_hash:
                    return IngestResult(record.id, current.id, current.version, created=False)
                version_number = current.version + 1

            version_id = self._ids.new()
            session.add(
                RecordVersionRow(
                    id=version_id,
                    record_id=record.id,
                    version=version_number,
                    kind=new.kind,
                    title=new.title,
                    content=new.content,
                    meta=new.metadata,
                    occurred_at=new.occurred_at,
                    ingested_at=self._clock.now(),
                    content_hash=content_hash,
                )
            )
            session.flush()
            session.add_all(
                RecordVersionAclRow(version_id=version_id, principal_id=entry)
                for entry in sorted(new.acl.principals)
            )
            self._index(session, version_id, new)
            record.current_version_id = version_id

            self._events.append(
                session,
                type="record.version_added",
                actor=SYSTEM,
                subject_type="record",
                subject_id=record.id,
                payload={
                    "version_id": version_id,
                    "version": version_number,
                    "source_id": new.source_id,
                    "external_id": new.external_id,
                    "content_hash": content_hash,
                },
            )
            return IngestResult(record.id, version_id, version_number, created=True)

    def _hash_and_check_size(self, new: NewRecord) -> str:
        payload = {
            "kind": new.kind,
            "title": new.title,
            "content": new.content,
            "metadata": new.metadata,
            "acl": sorted(new.acl.principals),
        }
        try:
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        except (TypeError, ValueError) as error:
            raise DomainError(
                "record_invalid", 422, "Record metadata must be plain JSON data."
            ) from error
        encoded = canonical.encode("utf-8")
        if len(encoded) > self._settings.max_record_bytes:
            raise DomainError(
                "record_too_large",
                413,
                f"Record exceeds the limit of {self._settings.max_record_bytes} bytes.",
            )
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _index(session: Session, version_id: str, new: NewRecord) -> None:
        rowid = session.execute(
            text("SELECT rowid FROM record_versions WHERE id = :id"), {"id": version_id}
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO record_fts (rowid, title, content) VALUES (:rowid, :title, :content)"
            ),
            {"rowid": rowid, "title": new.title, "content": new.content},
        )
