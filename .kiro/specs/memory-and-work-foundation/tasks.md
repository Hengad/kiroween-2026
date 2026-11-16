# Implementation Plan: Memory and work foundation

Every task is test-first: write the listed tests, run them and confirm they fail for the expected reason, then write the minimum code to pass, then refactor. After each task, `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy core/backend/src` must pass. Paths are under `core/backend/` (`src/siloless/...` and `tests/...`). Decisions D1 to D5 in `design.md` are settled.

- [x] 1. Foundations: clock, ids, errors, settings
  - Tests (`tests/unit/`): `ManualClock` returns aware UTC and advances only when told; `UlidGenerator` ids sort in creation order, including many ids in the same millisecond; a naive datetime is rejected by the UTC helper; `DomainError` carries code, status and extra members; `Settings` reads `SILOLESS_*` environment variables and has the defaults listed in the design.
  - Code: `clock.py`, `ids.py`, `errors.py`, `settings.py`; add `pydantic-settings` use (already a dependency).
  - _Requirements: 12.4, 2.6 (limits come from settings)_

- [x] 2. Access: principals and ACL rule (pure)
  - Tests (`tests/unit/access/`): a user expands to itself, its groups, its roles and `group:everyone`; the system principal allows everything; `Acl` rejects an empty set and malformed ids; `Acl.allows` is true exactly when the ACL and the expanded set share an entry.
  - Code: `access/principals.py` (`PrincipalId`, `ResolvedPrincipal`, `SYSTEM`, `EVERYONE`), `access/acl.py`.
  - _Requirements: 1.1, 1.3, 1.5, 2.6_

- [x] 3. Storage: database, models, schema
  - Tests (`tests/unit/storage/`, `tests/integration/`): an in-memory database can be created and a write transaction commits or rolls back as a unit; foreign keys are enforced; `install_schema` creates every table, the `record_fts` index and `group:everyone`; a raw `UPDATE` or `DELETE` on `events` fails; a relation row with both or neither endpoint column per side is rejected by the CHECK; a temporary file database uses WAL and write transactions use `BEGIN IMMEDIATE`.
  - Code: `storage/db.py`, `storage/models.py`, `storage/types.py` (`UtcDateTime`), `storage/schema.py`.
  - _Requirements: 6.4, 7.4, 12.6_

- [x] 4. Principal directory
  - Tests (`tests/unit/access/`): create and list principals; set memberships; `resolve` returns the expanded set; a membership change applies to the next `resolve`; resolving an unknown id raises `principal_unknown`.
  - Code: `PrincipalDirectory` in `access/principals.py`.
  - _Requirements: 1.2, 1.3, 1.4, 1.6_

- [x] 5. Event log
  - Tests (`tests/unit/events/`): `append` stamps the injected clock and returns events in append order; events for a subject are returned in order and respect `after_seq` and `limit`; there is no update or delete method; an event written in a transaction that rolls back does not exist.
  - Code: `events/log.py` (`append`, `for_subject` with the readability check wired in task 7 and task 9 as each subject type arrives; until then it supports subjects the caller marks readable).
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 6. Record ingestion and authority
  - Tests (`tests/unit/memory/`): a new Record gets an id and version 1 and is stored; the same payload again returns the same version, `created=False`, and appends no event; a changed title, content, metadata or ACL creates version N+1 and leaves earlier versions unchanged; a different `occurred_at` alone is not a change; reverting to an older payload creates a new version; missing field, oversized content and empty ACL are rejected and store nothing; exactly one version is current; `is_authoritative` is true only for a current version from a configured Source or kind, and false for everything when nothing is configured.
  - Code: `memory/domain.py` (`NewRecord`, `RecordVersion`), `memory/ingest.py`, `memory/authority.py`. Each ingest writes the ACL rows, the FTS row and a `record.version_added` event in one transaction.
  - _Requirements: 2.1 to 2.7, 3.1 to 3.4_

- [x] 7. Record reads with permission filtering
  - Tests: example tests in `tests/unit/memory/test_records.py` for `get_current`, `get_version` and `list_versions`, including that versions come back newest first with exactly one marked current and the rest superseded, and that an unreadable Record gives the same error as a missing one, and that tightening access in a new version hides older versions from the people who lost access. Property test `tests/properties/test_permission_safety.py` (first part): for random worlds of users, groups, Records and ACLs, every read returns exactly the oracle's readable set, and the oracle is `Acl.allows`. Add `tests/strategies.py` with the shared Hypothesis strategies.
  - Code: `access/filters.py` (`record_version_readable`), `memory/records.py` (`RecordReader`). Wire Record subjects into `EventLog.for_subject`.
  - _Requirements: 4.1 to 4.7, 7.6_

- [x] 8. Search
  - Tests: `tests/unit/memory/test_search.py`: matching by title and content, ranking, passage in the result, filters by Source, kind, time range and Entity (Entity filter is completed in task 9), no match returns an empty list, empty and over-long queries are rejected, a query containing quotes, `AND`, `*` and `NEAR(` is treated as plain words and does not error. Extend `test_permission_safety.py`: for any world, search results equal the readable current Records that match, no more and no fewer.
  - Code: `memory/search.py` (`RecordSearch` protocol and the FTS5 implementation with the ACL predicate in the same query).
  - _Requirements: 4.4, 5.1 to 5.5_

- [x] 9. Entities and Relations
  - Tests: `tests/unit/memory/test_graph.py`: unregistered types are rejected; an Entity upsert with the same type and key returns the existing Entity and updates it, appending an event only when name or attributes change; a Relation to a missing version or Entity is rejected and stores nothing; an identical Relation returns the existing one and appends no event; a Relation is visible only to Principals who can read every Record version it connects; Entity-to-Entity Relations are visible to everyone; reading an Entity lists only readable linked Records. Property test `tests/properties/test_referential_integrity.py`. Extend `test_permission_safety.py` for Relations and Entity links.
  - Code: `memory/graph.py` (`SchemaRegistry`, `EntityStore`, `RelationStore`), `relation_readable` in `access/filters.py`. Complete the Entity filter in search and wire Entity and Relation subjects into `EventLog.for_subject`.
  - _Requirements: 6.1 to 6.10_

- [x] 10. Work Item lifecycle and replay (pure)
  - Tests: `tests/unit/work/test_lifecycle.py`: each of the allowed edges in requirement 9.1 is accepted and every other pair of statuses is rejected with `invalid_transition`. `tests/unit/work/test_history.py`: replaying hand-built event lists gives the expected state, and a reopen clears `resolution` while the earlier event keeps it.
  - Code: `work/domain.py`, `work/lifecycle.py`, `work/history.py`.
  - _Requirements: 9.1, 9.2, 9.5, 11.2_

- [x] 11. Work Items: create, read, list
  - Tests (`tests/unit/work/test_items.py`): create with kind, title, description, due date and evidence; default status `open`; owner without status becomes `assigned`; owner with `awaiting_acceptance` is rejected; a missing evidence version is rejected and nothing is stored; creator and owner can always read the item; another Principal can read it only if they can read every evidence version (and never when there is no evidence); evidence links the reader cannot read are omitted; list filters by kind, status and owner, is newest first, and pages with `before` and `limit`. Extend `test_permission_safety.py` for Work Items.
  - Code: `work_item_readable` in `access/filters.py`, `work/items.py` (`create`, `get`, `list`). Wire Work Item subjects into `EventLog.for_subject`.
  - _Requirements: 8.1 to 8.7, 11.3, 11.4_

- [x] 12. Work Items: claim, assign, transition, history
  - Tests: `tests/unit/work/test_items.py`: claim on an open unowned item sets owner and `investigating`; a second claim fails with `already_owned` naming the owner; claim on a non-open item fails with `invalid_transition`; claim on an unreadable item is `not_found`; assign moves `open` and `reopened` to `assigned`, keeps status in `assigned`, `investigating` and `blocked`, rejects `awaiting_acceptance` and `resolved`, rejects non-user and unknown owners, and records the previous owner; resolve requires text and stores it; reopen clears it; `investigating` from `reopened` with no owner makes the actor the owner; `assigned` and `open` to `investigating` are not accepted through `transition`; history returns the item's events in order. Property tests: `test_valid_lifecycle.py` (a `RuleBasedStateMachine` checking the owner and status rules, model agreement and `replay(events) == stored state` after every step), `test_single_owner.py`, `test_append_only_history.py`. Integration `tests/integration/test_claim_concurrency.py`: eight threads claim one item on a temporary file database and exactly one succeeds, repeated 20 times.
  - Code: `claim`, `assign`, `transition`, `history` in `work/items.py`, using conditional `UPDATE`s.
  - _Requirements: 9.2 to 9.5, 10.1 to 10.7, 11.1, 11.2_

- [x] 13. API: principal handling, errors, principals, ingestion
  - Tests (`tests/integration/test_api_*.py`): missing, unknown and `system` principal headers give the documented codes; errors come back as `application/problem+json` with `code`; `PUT /principals/{id}`, `GET /principals` and `PUT /users/{id}/memberships` work; `POST /ingest/records`, `/ingest/entities` and `/ingest/relations` store data, are idempotent, and reject bad input with the documented codes and statuses.
  - Code: `api/deps.py`, `api/errors.py`, `api/schemas.py`, `api/routes/principals.py`, `api/routes/ingest.py`; `app.py` builds the `Database`, services and routers from `Settings`.
  - _Requirements: 1.5, 1.6, 2.x via HTTP, 12.1 to 12.5_

- [x] 14. API: reads, search, graph, events
  - Tests: records (current, versions, one version), search with each filter, entities with linked records, node relations and events endpoints; an unreadable object returns a response identical to a missing one; every read route returns 400 without a principal header.
  - Code: `api/routes/records.py`, `search.py`, `graph.py`, `events.py`.
  - _Requirements: 4.x, 5.x, 6.6, 6.7, 7.6, 12.1, 12.5_

- [x] 15. API: Work Items
  - Tests: create, list with filters and paging, get, claim (including a 409 with the owner), assign, transition (including resolution rules and invalid edges), history; full flow: create, claim, resolve, reopen, with the history showing each step.
  - Code: `api/routes/work_items.py`.
  - _Requirements: 8.x, 9.x, 10.x, 11.x, 12.1_

- [x] 16. Alembic migration
  - Tests: running the initial revision on a fresh temporary file creates the same tables, columns and constraints as `install_schema` on the ORM metadata, plus the FTS5 table and the event triggers.
  - Code: Alembic environment under `storage/migrations/` and the initial revision, which calls `install_schema`.
  - _Requirements: 12.6_

- [x] 17. Wrap-up
  - Tests: an OpenAPI contract test lists every route and the problem-details schema. The full suite, `ruff`, and `mypy --strict` pass.
  - Docs: update `README.md` status and commands, add `CHANGELOG.md` entries, note any design deviations in `design.md`, and add the `.env.example` for the settings.
  - _Requirements: 12.3_
