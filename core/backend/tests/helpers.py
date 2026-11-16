"""Shared test wiring: builds the engine services on a database."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from siloless.access.principals import PrincipalDirectory, ResolvedPrincipal
from siloless.clock import ManualClock
from siloless.events.log import EventLog
from siloless.ids import UlidGenerator
from siloless.memory.graph import (
    EntityStore,
    RelationStore,
    SchemaRegistry,
    can_read_entity,
    can_read_relation,
)
from siloless.memory.ingest import RecordIngestor
from siloless.memory.records import RecordReader, can_read_record
from siloless.memory.search import Fts5RecordSearch
from siloless.settings import Settings
from siloless.storage.db import Database
from siloless.work.items import WorkItemService, can_read_work_item


@dataclass
class Services:
    db: Database
    clock: ManualClock
    ids: UlidGenerator
    events: EventLog
    settings: Settings
    directory: PrincipalDirectory
    ingestor: RecordIngestor
    reader: RecordReader
    search: Fts5RecordSearch
    entities: EntityStore
    relations: RelationStore
    items: WorkItemService

    def add_user(self, user_id: str, memberships: Iterable[str] = ()) -> ResolvedPrincipal:
        """Create a user with groups and roles, and return it resolved."""
        targets = list(memberships)
        with self.db.transaction() as session:
            for target in targets:
                self.directory.put(session, target, target)
            self.directory.put(session, user_id, user_id)
            self.directory.set_memberships(session, user_id, targets)
        with self.db.transaction(write=False) as session:
            return self.directory.resolve(session, user_id)


def build_services(db: Database | None = None, **settings_overrides: Any) -> Services:
    database = db if db is not None else Database.in_memory()
    if db is None:
        database.create_schema()
    clock = ManualClock(datetime(2026, 11, 14, 12, 0, tzinfo=UTC))
    ids = UlidGenerator(clock)
    settings = Settings(_env_file=None, **settings_overrides)
    events = EventLog(clock, ids)
    events.register_subject_check("record", can_read_record)
    events.register_subject_check("entity", can_read_entity)
    events.register_subject_check("relation", can_read_relation)
    events.register_subject_check("work_item", can_read_work_item)
    directory = PrincipalDirectory()
    registry = SchemaRegistry(settings.entity_types, settings.relation_types)
    return Services(
        db=database,
        clock=clock,
        ids=ids,
        events=events,
        settings=settings,
        directory=directory,
        ingestor=RecordIngestor(database, clock, ids, events, settings),
        reader=RecordReader(database, settings),
        search=Fts5RecordSearch(database, settings),
        entities=EntityStore(database, ids, events, registry, settings),
        relations=RelationStore(database, ids, events, registry),
        items=WorkItemService(database, clock, ids, events, directory),
    )


def fresh_services(**settings_overrides: Any) -> Services:
    """Services on a new in-memory database with the schema installed."""
    database = Database.in_memory()
    database.create_schema()
    return build_services(database, **settings_overrides)
