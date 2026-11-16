"""Wires the engine's services together from Settings."""

from dataclasses import dataclass

from siloless.access.principals import PrincipalDirectory
from siloless.clock import Clock, SystemClock
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
class Container:
    settings: Settings
    db: Database
    clock: Clock
    events: EventLog
    directory: PrincipalDirectory
    ingestor: RecordIngestor
    reader: RecordReader
    search: Fts5RecordSearch
    entities: EntityStore
    relations: RelationStore
    items: WorkItemService


def build_container(settings: Settings, clock: Clock | None = None) -> Container:
    """Open the database, install the schema if needed, and create the services."""
    clock = clock if clock is not None else SystemClock()
    db = Database(settings.database_url)
    db.create_schema()
    ids = UlidGenerator(clock)
    events = EventLog(clock, ids)
    events.register_subject_check("record", can_read_record)
    events.register_subject_check("entity", can_read_entity)
    events.register_subject_check("relation", can_read_relation)
    events.register_subject_check("work_item", can_read_work_item)
    directory = PrincipalDirectory()
    registry = SchemaRegistry(settings.entity_types, settings.relation_types)
    return Container(
        settings=settings,
        db=db,
        clock=clock,
        events=events,
        directory=directory,
        ingestor=RecordIngestor(db, clock, ids, events, settings),
        reader=RecordReader(db, settings),
        search=Fts5RecordSearch(db, settings),
        entities=EntityStore(db, ids, events, registry, settings),
        relations=RelationStore(db, ids, events, registry),
        items=WorkItemService(db, clock, ids, events, directory),
    )
