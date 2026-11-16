# Design Document: Memory and work foundation

## Overview

This design implements `requirements.md` in the same order. It adds two infrastructure packages (`access/`, `storage/`) beside the existing module plan, and builds `memory/`, `work/` and `events/` on them. The HTTP layer stays thin.

Three ideas carry most of the design:

1. **One read filter, used everywhere.** Every query that returns Records, Relations or Work Items is built with a shared SQL predicate from `access/`. No repository method returns data without taking a `ResolvedPrincipal`.
2. **Compare-and-set for every state change.** Claims, assignments and transitions are single conditional `UPDATE` statements. Exactly one of several concurrent writers matches the `WHERE` clause. This works on SQLite and carries over to PostgreSQL.
3. **State changes and their events are written together, and events carry the state.** Each Work Item event stores the fields it changed, so the current state can be rebuilt by folding the events. That makes replay (requirement 11.2) a simple, testable property.

## Module layout

```
core/backend/src/siloless/
├── clock.py            Clock protocol, SystemClock, ManualClock (tests)
├── ids.py              IdGenerator protocol, UlidGenerator
├── errors.py           DomainError and stable error codes
├── settings.py         Settings (pydantic-settings)
├── access/
│   ├── principals.py   PrincipalId, ResolvedPrincipal, SYSTEM, EVERYONE, PrincipalDirectory
│   ├── acl.py          Acl value object and the pure allows() rule
│   └── filters.py      SQL predicates: record_version_readable, work_item_readable, relation_readable
├── storage/
│   ├── db.py           Database: engine, pragmas, transaction()
│   ├── models.py       SQLAlchemy ORM models
│   ├── types.py        UtcDateTime, JSON column helpers
│   ├── schema.py       install_schema(): tables, FTS5 index, event-log triggers
│   └── migrations/     Alembic environment and the initial revision
├── events/
│   └── log.py          EventLog.append(), EventLog.for_subject()
├── memory/
│   ├── domain.py       NewRecord, RecordVersion, Entity, Relation, NodeRef (frozen dataclasses)
│   ├── ingest.py       RecordIngestor
│   ├── records.py      RecordReader (get, versions)
│   ├── search.py       RecordSearch (FTS5 implementation behind a protocol)
│   ├── graph.py        SchemaRegistry, EntityStore, RelationStore
│   └── authority.py    is_authoritative()
├── work/
│   ├── domain.py       WorkItem, WorkItemState, enums
│   ├── lifecycle.py    TRANSITIONS and check_transition() (pure)
│   ├── history.py      replay() (pure)
│   └── items.py        WorkItemService
├── api/
│   ├── deps.py         principal dependency, service wiring
│   ├── errors.py       problem-details exception handlers
│   ├── schemas.py      Pydantic request and response models
│   └── routes/         ingest.py, records.py, search.py, graph.py, work_items.py, events.py, principals.py
└── app.py              create_app(settings) wires everything
```

`access/` and `storage/` are new. They are added to `architecture.md` and `structure.md`. Both `memory/` and `work/` need Principals and ACL filters, and putting them in `memory/` would make `work/` depend on it for access rules alone.

## Decisions to confirm

| # | Decision | Why | Alternative |
|---|---|---|---|
| D1 | Storage and domain services are **synchronous**. FastAPI route handlers are plain `def`, which it runs in a thread pool. WebSockets and connectors (later specs) stay async and call services through `run_in_threadpool`. | SQLite has one writer, so an async driver adds a dependency (`aiosqlite`) and complexity with no throughput gain. Synchronous transactions are simpler to reason about and to test with threads. | Async SQLAlchemy with `aiosqlite`. This departs from "Async for I/O" in `backend.md`; if you agree, I'll amend that line. |
| D2 | **Ingestion endpoints take no Principal.** Records, Entities and Relations are written under `/ingest/*` and are performed as the system Principal, with the Source named in the event. User-facing endpoints are reads and Work Item actions. | A simulation must feed the engine like a real Source would. Real connectors are trusted integrations, not users. | Require a Principal on every write and use a service account. More ceremony for no demo benefit. |
| D3 | Principal identifiers are readable strings, `user:anna`, `group:maintenance`, `role:shift-lead`. Generated entities use ULIDs. | Seed data and ACLs stay legible. Principals are named by the organization, not generated. | ULIDs for principals too. |
| D4 | Work Item `resolution` is cleared when an item is reopened. The earlier resolution stays in the Event Log. | Keeps "current state" and "history" separate, so replay stays a plain fold. | Keep the last resolution on the item. |
| D5 | Relations attach to a **specific Record version**. A connector that ingests a new version also re-asserts that version's links. | Citations and evidence name exact versions. | Attach relations to the logical Record. Easier for connectors, but links would then silently apply to text they were never made for. |

## Core building blocks

### Time and identifiers

- `Clock.now() -> datetime` returns a timezone-aware UTC value. `ManualClock` is advanced explicitly in tests.
- `IdGenerator.new() -> str`. `UlidGenerator` builds a ULID from the clock's millisecond time plus 80 random bits (injected `os.urandom`-style callable). It is monotonic: within the same millisecond it increments the random part, so ULIDs always sort in creation order. No new dependency.
- Stored timestamps use a `UtcDateTime` column type that rejects naive values on the way in and returns UTC-aware values on the way out, since SQLite drops time zones.

### Errors

`DomainError(code, status, detail, extra)` is the only exception type routes translate. Codes are stable strings, listed under "Error codes". The API layer turns them into RFC 9457 problem details (`application/problem+json`).

### Settings

`Settings` (pydantic-settings, env prefix `SILOLESS_`):

| Field | Default | Used by |
|---|---|---|
| `database_url` | `sqlite:///siloless.db` | storage |
| `max_record_bytes` | 262144 | ingest (2.6) |
| `max_query_length` | 256 | search (5.5) |
| `authoritative_sources` | `[]` | authority (3.1) |
| `authoritative_kinds` | `[]` | authority (3.1) |
| `entity_types` | `[]` | schema registry (6.2) |
| `relation_types` | the built-in set below, plus any listed | schema registry (6.2) |

Built-in relation types: `mentions`, `about`, `caused_by`, `resolves`, `answers`, `supersedes`, `duplicate_of`, `located_at`. Applications add Entity types and more Relation types through settings. A Plugin parameter on `create_app` is added when the first extension needs it, not now.

## Access (`access/`)

### Principals

```python
PrincipalId = str  # "user:anna", "group:maintenance", "role:shift-lead", "system"


@dataclass(frozen=True)
class ResolvedPrincipal:
    id: PrincipalId  # the acting identity (a user, or SYSTEM)
    ids: frozenset[PrincipalId]  # id + groups + roles + "group:everyone"
    is_system: bool = False
```

`PrincipalDirectory` reads `principals` and `memberships` and exposes `resolve(id) -> ResolvedPrincipal`. It raises `principal_unknown` for an id that is not stored. `EVERYONE = "group:everyone"` is added to every user's `ids` (requirement 1.3). `SYSTEM` is never stored, can never be returned for a request header (the API dependency rejects it), and its `is_system=True` makes read filters match everything.

Membership changes take effect immediately because `resolve` reads the tables on every request. There is no cache.

### ACL

```python
@dataclass(frozen=True)
class Acl:
    principals: frozenset[PrincipalId]  # non-empty, validated on construction

    def allows(self, who: ResolvedPrincipal) -> bool:
        return who.is_system or bool(self.principals & who.ids)
```

`Acl.allows` is the single pure statement of the rule. It is the **oracle** for property tests, and the SQL predicates in `filters.py` must agree with it. A test generates random worlds and checks that agreement.

### SQL read filters

`filters.py` returns SQLAlchemy boolean expressions. Principal ids go in as bound parameters, never as formatted text.

- `record_version_readable(who)`: a version `v` of record `r` is readable when `who` satisfies `v`'s own ACL **and** the ACL of `r`'s current version (requirement 4.5):

  ```sql
  EXISTS (SELECT 1 FROM record_version_acl a
          WHERE a.version_id = v.id AND a.principal_id IN (:ids))
  AND EXISTS (SELECT 1 FROM record_version_acl a2
              WHERE a2.version_id = r.current_version_id AND a2.principal_id IN (:ids))
  ```

  For the current version the two clauses are the same row set. The system principal skips the filter.
- `relation_readable(who)`: for each endpoint, `endpoint_is_entity OR record_version_readable(endpoint)`. Both endpoints must pass (requirement 6.5). Entity endpoints are always readable (6.8).
- `work_item_readable(who)`: `created_by = :me OR owner = :me OR (has_evidence AND NOT EXISTS (evidence whose version is NOT readable))`. A Work Item with no evidence is readable only through the first two terms (8.7).

## Storage (`storage/`)

### Database and transactions

`Database` owns the engine and offers `transaction(write: bool)` as a context manager yielding a `Session`.

- Every connection runs `PRAGMA foreign_keys=ON` and `busy_timeout`; file databases also use `journal_mode=WAL`.
- pysqlite's default transaction handling interferes with explicit `BEGIN`. The engine uses the documented SQLAlchemy recipe: `isolation_level=None` on connect, with `BEGIN` issued from a `begin` event. Write transactions issue `BEGIN IMMEDIATE`, so two writers queue instead of failing late with a lock upgrade error. Read transactions use a plain deferred `BEGIN`.
- In-memory databases (unit tests) use one shared connection (`StaticPool`). Tests that need real concurrency use a temporary file database, as `tdd.md` requires.

### Schema

| Table | Key columns | Notes |
|---|---|---|
| `principals` | `id` PK, `type` (`user`/`group`/`role`), `name` | `group:everyone` is seeded by `install_schema` |
| `memberships` | (`user_id`, `target_id`) PK | `target_id` is a group or role principal |
| `records` | `id` PK, `source_id`, `external_id`, `current_version_id` FK | `UNIQUE(source_id, external_id)` |
| `record_versions` | `id` PK, `record_id` FK, `version`, `kind`, `title`, `content`, `metadata` JSON, `occurred_at`, `ingested_at`, `content_hash` | `UNIQUE(record_id, version)`, `UNIQUE(record_id, content_hash)` is **not** set, because reverting to old text is a legitimate new version |
| `record_version_acl` | (`version_id`, `principal_id`) PK | one row per ACL entry, indexed on `principal_id` |
| `record_fts` | FTS5 virtual table over `title`, `content`; `rowid` = version rowid | created by `install_schema`, maintained by the ingestor in the same transaction |
| `entities` | `id` PK, `entity_type`, `key`, `name`, `attributes` JSON | `UNIQUE(entity_type, key)` |
| `relations` | `id` PK, `relation_type`, `from_version_id`, `from_entity_id`, `to_version_id`, `to_entity_id` | each side has two nullable foreign keys with `CHECK ((a IS NULL) <> (b IS NULL))`. Foreign keys give referential integrity (6.4) without polymorphic references. `UNIQUE(relation_type, from_*, to_*)` |
| `work_items` | `id` PK, `kind`, `title`, `description`, `status`, `owner`, `created_by`, `due_at`, `resolution`, `created_at`, `updated_at` | CHECKs on `kind` and `status` values |
| `work_item_evidence` | (`work_item_id`, `version_id`) PK | foreign keys to both |
| `events` | `seq` INTEGER PK AUTOINCREMENT, `id` ULID, `occurred_at`, `type`, `actor`, `subject_type`, `subject_id`, `payload` JSON | indexed on (`subject_type`, `subject_id`, `seq`) |

Authoritativeness is **computed**, not stored (see Memory). Principal ids and the "current version" pointer are the only denormalized facts.

### Event log protection

`install_schema` also creates two triggers on `events`, `BEFORE UPDATE` and `BEFORE DELETE`, that `RAISE(ABORT, 'events are append-only')`. The repository has no update or delete method either. The triggers are a second line of defense (requirement 7.4), and a test attempts raw `UPDATE`/`DELETE` and expects failure. Triggers are dialect-specific, so a PostgreSQL port needs its own migration for them.

### Migrations

Alembic is set up with one initial revision. It creates the tables from the ORM metadata and calls the same `install_schema` helper for the FTS5 table, the triggers and seed rows. Tests build schemas with `install_schema` for speed. One test runs the Alembic revision on a fresh file and compares the resulting schema with the ORM metadata, so the two cannot drift apart.

## Events (`events/`)

```python
EventLog.append(session, *, type, actor, subject_type, subject_id, payload) -> Event
EventLog.for_subject(session, who, subject_type, subject_id, after_seq=0, limit=200) -> list[Event]
```

`append` runs inside the caller's transaction and stamps the time from the injected clock. It is the only write path to `events`.

`for_subject` first checks the subject is readable by `who`, using the filter for that subject type: a Record uses its current version, a Relation uses `relation_readable`, a Work Item uses `work_item_readable`, and an Entity is always readable. If the subject is not readable the result is empty, the same as for a subject that does not exist (7.6). Payloads hold identifiers, hashes and changed fields only, never Record content, so an event does not leak text its subject's readers could not otherwise see.

### Event types

| Type | Subject | Payload |
|---|---|---|
| `record.version_added` | record | `version_id`, `version`, `source_id`, `external_id`, `content_hash` |
| `entity.created` / `entity.updated` | entity | `entity_type`, `key`, and for updates the changed fields |
| `relation.created` | relation | `relation_type`, both endpoints |
| `work_item.created` | work_item | `changes`: every initial field |
| `work_item.claimed` | work_item | `changes`: `owner`, `status`; `before` |
| `work_item.assigned` | work_item | `changes`: `owner` and, if it moved, `status`; `before` |
| `work_item.status_changed` | work_item | `changes`: `status` and, where relevant, `resolution`, `owner`; `before` |

## Memory (`memory/`)

### Ingestion

`RecordIngestor.ingest(new: NewRecord, source_actor) -> IngestResult(record_id, version_id, version, created)` runs in one write transaction:

1. Validate: required fields present, serialized size at most `max_record_bytes`, ACL non-empty and every entry a well-formed principal id. Failures raise `record_invalid`, `record_too_large` or `acl_empty` before anything is written (2.6).
2. Compute `content_hash`: SHA-256 of a canonical JSON form (sorted keys) of `kind`, `title`, `content`, `metadata` and the sorted ACL. `occurred_at` is excluded, because a re-delivery of the same item with a different timestamp is not a change (2.3, 2.4).
3. Look up the record by (`source_id`, `external_id`).
   - Not found: insert the record and version 1.
   - Found and the current version has the same hash: return it with `created=False`. Nothing is written and no event is appended (2.3).
   - Found with a different hash: insert version N+1, point `current_version_id` at it, and leave older versions untouched (2.4, 2.5).
4. Insert ACL rows and the FTS row for the new version, append `record.version_added`.

Two concurrent first-time ingests of the same item hit the `UNIQUE(source_id, external_id)` constraint. `BEGIN IMMEDIATE` already serializes writers on SQLite. For PostgreSQL the ingestor catches `IntegrityError` once, re-reads, and continues. Re-ingesting an older payload after a change creates a new version, because it differs from the current one.

Record content is stored and indexed as text and never interpreted (2.7). Search snippets are returned as plain text with the match markers as separate fields, not as HTML.

### Authority

`is_authoritative(version, is_current, settings)` is a pure function: `is_current and (source in settings.authoritative_sources or kind in settings.authoritative_kinds)`. It is evaluated when a Record is returned, so a newer version automatically removes authority from the older one (3.3) and an empty configuration yields no authoritative Records (3.4).

### Reading

`RecordReader` takes a `ResolvedPrincipal` on every method: `get_current(record_id)`, `get_version(version_id)`, `list_versions(record_id)`. Every returned `RecordVersion` carries `is_current` (true when `records.current_version_id` points at it), and `list_versions` orders by version number descending, so the UI can highlight the latest. Each runs one query with `record_version_readable` in the `WHERE` clause. A Record that exists but is unreadable and a Record that does not exist both raise the same `not_found` error with the same message (4.3).

### Search

`RecordSearch` is a protocol with one method, `search(who, SearchQuery) -> list[SearchHit]`, so the PostgreSQL port can swap in its own full-text implementation. The FTS5 implementation builds one query:

- **Query text** is split into tokens, each token is wrapped in double quotes with internal quotes doubled, and the tokens are joined with spaces (implicit AND). User input therefore cannot inject FTS5 syntax or cause a syntax error. An empty query or one longer than `max_query_length` raises `query_invalid` (5.5).
- **Filters** join `record_fts` to `record_versions` and `records`, restricted to `records.current_version_id = record_versions.id`, plus `record_version_readable(who)` and the optional Source, kind, time range and Entity filters (5.2). The Entity filter requires a Relation linking that version to the Entity in either direction.
- **Ranking and passage** use `bm25()` and `snippet()` in the same `SELECT`. Because the ACL predicate is in the same statement, a snippet can only be produced for a row the Principal may read, and no count or rank reflects unreadable rows (4.4).
- Results carry `record_id`, `version_id`, `version`, `title`, `passage`, `source_id` and `is_authoritative` (5.4). The default `limit` is 20 and the maximum 100.

### Entities and Relations

`SchemaRegistry` holds the registered Entity and Relation type names from settings. Unregistered types raise `unknown_entity_type` or `unknown_relation_type` (6.2).

- `EntityStore.upsert(type, key, name, attributes)` inserts, or returns the existing Entity unchanged, or updates it and appends `entity.updated` only when name or attributes differ (6.10).
- `RelationStore.create(type, from_node, to_node)` takes `NodeRef(kind: "record_version" | "entity", id)` endpoints, maps each to the matching nullable column, and relies on foreign keys for existence; a violation becomes `node_not_found` and nothing is stored (6.4). An existing identical relation is returned with no new event (6.9).
- `RelationStore.for_node(who, node)` applies `relation_readable` (6.6). `EntityStore.get(who, id)` returns the Entity and, separately, the linked Records filtered by `record_version_readable`, omitting the rest without any placeholder (6.7).

## Work (`work/`)

### Domain

```python
WorkItemKind   = "question" | "request" | "incident" | "action"
WorkItemStatus = "awaiting_acceptance" | "open" | "assigned" | "investigating"
               | "blocked" | "resolved" | "reopened"
```

`WorkItemState` is the frozen record of `status`, `owner`, `resolution` and the descriptive fields. Two structural rules always hold, and tests check them after every operation:

- `status` in {`assigned`, `investigating`, `blocked`} implies an owner exists.
- `status` in {`open`, `awaiting_acceptance`} implies no owner.

`resolved` and `reopened` keep whatever owner the item had.

### Lifecycle (pure)

`TRANSITIONS: dict[Status, frozenset[Status]]` encodes requirement 9.1 exactly. `check_transition(old, new)` raises `invalid_transition` for anything else. It has no database access, so it is unit-tested and property-tested directly.

### Service

`WorkItemService` takes the `Database`, clock, id generator, `EventLog` and `PrincipalDirectory`. Each public method is one write transaction that applies the change and appends its event.

- `create(who, NewWorkItem)`: checks every evidence version exists (else `node_not_found`). Initial status is `open`, `awaiting_acceptance`, or `assigned` when an owner is supplied without a status; an owner together with `awaiting_acceptance` is rejected (8.3). Evidence rows and the `work_item.created` event are written together.
- `get`, `list`: both use `work_item_readable`. `get` omits evidence links whose version the Principal cannot read (8.5). `list` supports `kind`, `status` and `owner` filters, orders by `id DESC` (ULIDs sort by creation time, giving a stable newest-first order), and pages with a `before` cursor and `limit` (default 50, maximum 200).
- `claim(who, id)`: first confirms the item is readable (else `not_found`). Then it runs one statement:

  ```sql
  UPDATE work_items SET owner = :me, status = 'investigating', updated_at = :now
  WHERE id = :id AND owner IS NULL AND status = 'open'
  ```

  `rowcount == 1` means this caller won, and `work_item.claimed` is appended in the same transaction. `rowcount == 0` means the row changed first: the service re-reads, and raises `already_owned` (with the owner in the problem body) if an owner exists, otherwise `invalid_transition`. Of any number of concurrent claims, exactly one matches the `WHERE` clause (10.1, 10.2, 10.3, 10.4).
- `assign(who, id, new_owner)`: the new owner must be an existing `user:` principal (`owner_must_be_user`, `owner_unknown`). Allowed from `open` and `reopened` (status becomes `assigned`), and from `assigned`, `investigating` and `blocked` (status unchanged). It is rejected from `awaiting_acceptance` and `resolved` with `not_assignable` (10.7). The update is conditional on the status it read, and the previous owner is written into the event's `before` (10.5).
- `transition(who, id, to, resolution=None)`: `check_transition` first, then a conditional update on the status that was read, retried up to three times on a lost race and then raised as `concurrent_modification`. Targets and side effects:
  - `resolved` requires non-empty `resolution` (`resolution_required`) and stores it (9.4).
  - `reopened` clears the stored `resolution`; the earlier text remains in the log (9.5, D4).
  - `investigating` from `assigned`, `blocked` or `reopened` sets the actor as owner when the item has none.
  - `assigned` is not a valid target here, because it needs an owner; callers use `assign`. `open` to `investigating` is not valid here either; callers use `claim`.
  - Every accepted transition records actor, time, old and new status in the event (9.3).

### History and replay

`history.replay(events) -> WorkItemState` folds the `changes` dictionaries of the item's events in order. `WorkItemService.history(who, id)` returns the events through `EventLog.for_subject` (11.1). The property test asserts `replay(events) == stored state` after any operation sequence (11.2).

## API (`api/`)

### Principal handling

The `principal` dependency reads the `X-Principal-Id` header. The name is a constant, not a setting, because it is declared as an OpenAPI security scheme so the `/docs` page can send it. An unreadable request body gets `request_invalid` (422). A missing header returns `principal_required` (400). An unknown id returns `principal_unknown` (403). The id `system` returns `principal_forbidden` (403) (1.5, 1.6). The result is a `ResolvedPrincipal`. Routes that read or act on behalf of a user require it. `/ingest/*`, `/principals`, `/users/*/memberships` and `/health` do not. There is no authentication in this spec, so the header is trusted.

### Endpoints

| Method and path | Principal | Purpose |
|---|---|---|
| `GET /health` | no | liveness (exists) |
| `PUT /principals/{id}` | no | create or update a principal: `type`, `name` |
| `GET /principals` | no | list principals (the frontend needs assignee names) |
| `PUT /users/{id}/memberships` | no | replace a user's group and role memberships |
| `POST /ingest/records` | no | ingest a Record (acts as system) |
| `POST /ingest/entities` | no | upsert an Entity |
| `POST /ingest/relations` | no | create a Relation |
| `GET /records/{record_id}` | yes | current version |
| `GET /records/{record_id}/versions` | yes | readable versions |
| `GET /record-versions/{version_id}` | yes | one version |
| `GET /search` | yes | `q`, `source`, `kind`, `from`, `to`, `entity`, `limit` |
| `GET /entities/{id}` | yes | Entity plus readable linked Records |
| `GET /nodes/{node_type}/{node_id}/relations` | yes | readable Relations |
| `POST /work-items` | yes | create |
| `GET /work-items` | yes | list: `kind`, `status`, `owner`, `before`, `limit` |
| `GET /work-items/{id}` | yes | read |
| `POST /work-items/{id}/claim` | yes | claim |
| `POST /work-items/{id}/assign` | yes | body `{owner}` |
| `POST /work-items/{id}/transition` | yes | body `{to, resolution?}` |
| `GET /work-items/{id}/history` | yes | events for the item |
| `GET /events` | yes | `subject_type`, `subject_id`, `after_seq`, `limit` |

Routes are plain `def` handlers (D1). Pydantic schemas validate input, call one service method, and map the domain object to a response model. The OpenAPI document is generated by FastAPI and consumed by `openapi-typescript` in the frontend spec (12.3).

### Error codes

All errors use `application/problem+json` with `type`, `title`, `status`, `detail` and `code`. Where noted, extra members carry data.

| Code | Status | When |
|---|---|---|
| `principal_required` | 400 | missing principal header |
| `principal_unknown` | 403 | header names an unknown principal |
| `principal_forbidden` | 403 | header names the system principal |
| `record_invalid` | 422 | missing or malformed Record field |
| `record_too_large` | 413 | over `max_record_bytes` |
| `acl_empty` | 422 | empty ACL |
| `query_invalid` | 422 | empty or over-long search text |
| `unknown_entity_type`, `unknown_relation_type` | 422 | type not registered |
| `node_not_found` | 422 | relation endpoint or evidence link does not exist |
| `not_found` | 404 | missing **or unreadable** object, with identical body |
| `invalid_transition` | 409 | edge not in the lifecycle graph, or claim on a non-open item |
| `already_owned` | 409 | claim on an owned item; extra member `owner` |
| `not_assignable` | 409 | assign in `awaiting_acceptance` or `resolved` |
| `owner_must_be_user`, `owner_unknown` | 422 | bad assignee |
| `resolution_required` | 422 | resolve without text |
| `concurrent_modification` | 409 | conditional update lost after retries |

## Testing strategy

Everything is test-first (`tdd.md`). Test files mirror source paths.

### Unit (`tests/unit/`, in-memory SQLite or no database)

- `access/test_acl.py`, `test_principals.py`: expansion, `everyone`, system principal, ACL rule.
- `work/test_lifecycle.py`: every allowed edge accepted, every other edge rejected.
- `work/test_history.py`: replay of hand-built event lists.
- `memory/test_authority.py`, `test_ingest.py`, `test_search.py` (query tokenizing and quoting), `test_graph.py`.
- `test_ids.py`, `test_clock.py`: ULID ordering and monotonicity, UTC enforcement.
- `events/test_log.py`: append, order, and that raw `UPDATE`/`DELETE` on `events` fail.

### Property-based (`tests/properties/`)

Strategies live once in `tests/strategies.py`: principal ids, memberships, ACLs, `NewRecord`, evidence picks, and operation sequences. An **oracle** (`Acl.allows` over the generated data) is the independent definition of "readable".

| File | Property | Requirements |
|---|---|---|
| `test_permission_safety.py` | For any world and any Principal, `get`, `versions`, `search`, relations, Entity links, events and Work Items return exactly the oracle's readable set: nothing extra (safety) and nothing missing (completeness). A second property tightens a Record's ACL in a new version and checks older versions disappear for the removed principals. A third checks that "unreadable" and "nonexistent" produce byte-identical errors. | 4, 5, 6, 7, 8 |
| `test_idempotent_ingestion.py` | For any sequence of payloads for one item, the number of versions equals the number of times the payload hash changed from the previous one; exactly one version is current; at most one is authoritative. | 2, 3 |
| `test_referential_integrity.py` | Relations with random endpoints are stored only when both exist. | 6 |
| `test_valid_lifecycle.py` | A `RuleBasedStateMachine` issues random create, claim, assign and transition calls. The model predicts accept or reject from `TRANSITIONS`. After every step: the structural owner/status rules hold, the stored state equals the model, and `replay(events)` equals the stored state. | 9, 10, 11 |
| `test_single_owner.py` | For any set of principals claiming in any order, exactly one claim succeeds and the others receive `already_owned` naming the winner. | 10 |
| `test_append_only_history.py` | After any operation sequence, previously read events are unchanged and sequence numbers only grow. | 7 |

When Hypothesis finds a failure, the minimal example is kept as an explicit regression test.

### Integration (`tests/integration/`)

- **Real concurrency** on a temporary file database: eight threads claim one item; exactly one succeeds. Repeated several times.
- API tests through the ASGI client for each endpoint, including the problem-details bodies and the principal header cases.
- A migration test: Alembic revision on a fresh file equals the ORM metadata.
- A contract test that the OpenAPI document contains every route and the error schema.

### Quality gates

`ruff check`, `ruff format --check` and `mypy --strict` on `core/backend/src` must pass for each task.

## Risks and open points

- **Entities are readable by everyone** (6.8). Names and attributes of Entities, such as machine names, are not access-controlled. Fine for the demo; a later spec could add Entity ACLs.
- **FTS5 syntax is SQLite-specific.** It is isolated behind `RecordSearch`, and the triggers and index creation live in `install_schema`, so a PostgreSQL port replaces those two places and nothing else.
- **No pagination cursor for search.** Search returns the top `limit` ranked results. Add paging only if the frontend needs it.
- **Every request resolves memberships from the database.** Fine at demo scale. A short-lived cache can be added later behind `PrincipalDirectory` if profiling shows a need.

## Deviations from this design

Where the implementation differs from what is written above, and why.

- **No retry loop on lost races.** Claims, assignments and transitions are single conditional `UPDATE`s, and a lost race raises `concurrent_modification` (409) instead of retrying up to three times. `BEGIN IMMEDIATE` already serializes writers on SQLite, so a retry has nothing to catch. A PostgreSQL port should add the retry.
- **Evidence order is stored.** `work_item_evidence` has a `position` column so evidence comes back in the order the creator listed it.
- **Evidence must be readable by the creator.** Creating a Work Item that cites a version the creator cannot read fails with `node_not_found`, the same as a missing version, so creation cannot be used to probe for ids.
- **An owner and a status cannot be combined at creation.** Requirement 8.3 only defined owner without status. Owner with `open` or `awaiting_acceptance` would break the rule that those statuses have no owner, so it is rejected with `work_item_invalid`.
- **Extra error codes.** `principal_invalid`, `entity_invalid`, `work_item_invalid` and `request_invalid` (any request body or parameter that fails schema validation) were added to the table, and `ProblemDetails` is the default response of every operation in the OpenAPI description.
- **The event log does not import memory or work.** Each module registers a readability check per subject type (`EventLog.register_subject_check`), and a subject type without a check is denied.
- **Relation identity uses an expression index.** `NULL`s are distinct inside a `UNIQUE` constraint, so identity is enforced on an index that maps `NULL` to an empty string.
- **The Alembic baseline calls `install_schema`.** It is safe to run on a database the application already created, which it then adopts without changing anything.
- **Not built:** a PostgreSQL implementation, the retry on lost races, and per-Entity access control (requirement 6.8).
