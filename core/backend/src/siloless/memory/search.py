"""Full-text search over the current version of every readable Record."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import ColumnClause, and_, column, func, literal, literal_column, or_, select, table

from siloless.access.filters import record_version_readable
from siloless.access.principals import ResolvedPrincipal
from siloless.errors import DomainError
from siloless.memory.authority import is_authoritative
from siloless.settings import Settings
from siloless.storage.db import Database
from siloless.storage.models import RecordRow, RecordVersionRow, RelationRow

MAX_LIMIT = 100
_WORD = re.compile(r"\w+")

# The FTS5 virtual table, described just enough to join against.
_fts = table("record_fts", column("rowid"), column("title"), column("content"))
_fts_name: ColumnClause[Any] = literal_column("record_fts")
_version_rowid: ColumnClause[Any] = literal_column("record_versions.rowid")


@dataclass(frozen=True)
class SearchQuery:
    text: str
    source_id: str | None = None
    kind: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    entity_id: str | None = None
    limit: int = 20


@dataclass(frozen=True)
class SearchHit:
    record_id: str
    version_id: str
    version: int
    title: str
    passage: str
    source_id: str
    kind: str
    is_authoritative: bool


class RecordSearch(Protocol):
    """A different database supplies its own implementation of this one method."""

    def search(self, who: ResolvedPrincipal, query: SearchQuery) -> list[SearchHit]: ...


class Fts5RecordSearch:
    """SQLite FTS5 search.

    The permission filter is part of the same statement as the text match, so a
    passage is only ever produced for a version the caller may read, and neither
    the ranking nor the number of results reflects Records the caller cannot read.
    """

    def __init__(self, db: Database, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def search(self, who: ResolvedPrincipal, query: SearchQuery) -> list[SearchHit]:
        match_text = self._to_match_expression(query.text)
        passage = func.snippet(_fts_name, -1, "", "", "...", 16).label("passage")

        statement = (
            select(
                RecordRow.id.label("record_id"),
                RecordVersionRow.id.label("version_id"),
                RecordVersionRow.version,
                RecordVersionRow.title,
                RecordVersionRow.kind,
                RecordRow.source_id,
                passage,
            )
            .select_from(_fts)
            .join(RecordVersionRow, _version_rowid == _fts.c.rowid)
            .join(
                RecordRow,
                and_(
                    RecordRow.id == RecordVersionRow.record_id,
                    RecordRow.current_version_id == RecordVersionRow.id,
                ),
            )
            .where(_fts_name.op("MATCH")(literal(match_text)), record_version_readable(who))
            .order_by(func.bm25(_fts_name))
            .limit(max(1, min(query.limit, MAX_LIMIT)))
        )
        if query.source_id is not None:
            statement = statement.where(RecordRow.source_id == query.source_id)
        if query.kind is not None:
            statement = statement.where(RecordVersionRow.kind == query.kind)
        if query.occurred_from is not None:
            statement = statement.where(RecordVersionRow.occurred_at >= query.occurred_from)
        if query.occurred_to is not None:
            statement = statement.where(RecordVersionRow.occurred_at <= query.occurred_to)
        if query.entity_id is not None:
            linked_out = (
                select(1)
                .where(
                    RelationRow.from_version_id == RecordVersionRow.id,
                    RelationRow.to_entity_id == query.entity_id,
                )
                .exists()
            )
            linked_in = (
                select(1)
                .where(
                    RelationRow.to_version_id == RecordVersionRow.id,
                    RelationRow.from_entity_id == query.entity_id,
                )
                .exists()
            )
            statement = statement.where(or_(linked_out, linked_in))

        with self._db.transaction(write=False) as session:
            rows = session.execute(statement).all()

        return [
            SearchHit(
                record_id=row.record_id,
                version_id=row.version_id,
                version=row.version,
                title=row.title,
                passage=row.passage,
                source_id=row.source_id,
                kind=row.kind,
                is_authoritative=is_authoritative(
                    source_id=row.source_id,
                    kind=row.kind,
                    is_current=True,
                    authoritative_sources=self._settings.authoritative_sources,
                    authoritative_kinds=self._settings.authoritative_kinds,
                ),
            )
            for row in rows
        ]

    def _to_match_expression(self, text: str) -> str:
        """Turn user text into a safe FTS5 expression: every word quoted, all required.

        Quotes, operators, column filters and wildcards in the user's text become
        plain words (or disappear), so user input can never act as search syntax."""
        if len(text) > self._settings.max_query_length:
            raise DomainError(
                "query_invalid",
                422,
                f"Search text is longer than {self._settings.max_query_length} characters.",
            )
        words = _WORD.findall(text)
        if not words:
            raise DomainError("query_invalid", 422, "Search text must contain at least one word.")
        return " ".join(f'"{word}"' for word in words)
