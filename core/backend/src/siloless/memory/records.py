"""Reading Records and their versions on behalf of a Principal."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from siloless.access.filters import record_version_readable
from siloless.access.principals import ResolvedPrincipal
from siloless.errors import not_found
from siloless.memory.authority import is_authoritative
from siloless.memory.domain import RecordVersion
from siloless.settings import Settings
from siloless.storage.db import Database
from siloless.storage.models import RecordRow, RecordVersionRow


class RecordReader:
    """Every method takes the requesting Principal, and the permission filter is part
    of the query itself. A Record the caller may not read raises the same `not_found`
    as a Record that does not exist."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def get_current(self, who: ResolvedPrincipal, record_id: str) -> RecordVersion:
        query = (
            select(RecordVersionRow, RecordRow)
            .join(RecordRow, RecordRow.current_version_id == RecordVersionRow.id)
            .where(RecordRow.id == record_id, record_version_readable(who))
        )
        with self._db.transaction(write=False) as session:
            found = session.execute(query).first()
        if found is None:
            raise not_found()
        return self._to_version(*found)

    def get_version(self, who: ResolvedPrincipal, version_id: str) -> RecordVersion:
        query = (
            select(RecordVersionRow, RecordRow)
            .join(RecordRow, RecordRow.id == RecordVersionRow.record_id)
            .where(RecordVersionRow.id == version_id, record_version_readable(who))
        )
        with self._db.transaction(write=False) as session:
            found = session.execute(query).first()
        if found is None:
            raise not_found()
        return self._to_version(*found)

    def list_versions(self, who: ResolvedPrincipal, record_id: str) -> list[RecordVersion]:
        """Every readable version, newest first, with the newest marked current."""
        query = (
            select(RecordVersionRow, RecordRow)
            .join(RecordRow, RecordRow.id == RecordVersionRow.record_id)
            .where(RecordRow.id == record_id, record_version_readable(who))
            .order_by(RecordVersionRow.version.desc())
        )
        with self._db.transaction(write=False) as session:
            rows = session.execute(query).all()
        if not rows:
            raise not_found()
        return [self._to_version(version, record) for version, record in rows]

    def _to_version(self, version: RecordVersionRow, record: RecordRow) -> RecordVersion:
        return to_record_version(version, record, self._settings)


def to_record_version(
    version: RecordVersionRow, record: RecordRow, settings: Settings
) -> RecordVersion:
    """Map stored rows to the read model, marking the newest version current."""
    current = record.current_version_id == version.id
    return RecordVersion(
        record_id=record.id,
        version_id=version.id,
        version=version.version,
        source_id=record.source_id,
        external_id=record.external_id,
        kind=version.kind,
        title=version.title,
        content=version.content,
        metadata=version.meta,
        occurred_at=version.occurred_at,
        ingested_at=version.ingested_at,
        is_current=current,
        is_authoritative=is_authoritative(
            source_id=record.source_id,
            kind=version.kind,
            is_current=current,
            authoritative_sources=settings.authoritative_sources,
            authoritative_kinds=settings.authoritative_kinds,
        ),
    )


def can_read_record(session: Session, who: ResolvedPrincipal, record_id: str) -> bool:
    """Readability check for events whose subject is a Record: its current version."""
    query = (
        select(RecordRow.id)
        .join(RecordVersionRow, RecordVersionRow.id == RecordRow.current_version_id)
        .where(RecordRow.id == record_id, record_version_readable(who))
    )
    return session.execute(query).first() is not None
