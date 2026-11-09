---
inclusion: always
---

# Engine architecture and domain language

Use these terms consistently in code, tests, API names and UI. If a new concept is needed, add it here first.

## Domain language

### Memory

| Term | Meaning |
|---|---|
| **Source** | An external system Siloless reads from (mailbox, chat workspace, document store, ticket tool, inventory, schedule, website, sensor feed, simulation). The built-in communication channel is also a Source. |
| **Connector** | Adapter that pulls or receives data from one Source and turns it into Records. Also maps the Source's permissions to an ACL. |
| **Record** | A normalized unit of information: a message, an email, a document version, an inventory row, a schedule entry, a measurement, an event. Immutable once stored; changes create a new version. |
| **Authoritative Record** | A Record that is the latest version of its document and comes from a Source or document type configured as authoritative. Only authoritative Records can produce an `answered` outcome. |
| **Entity** | A real-world thing Records talk about: a machine, a production stage, a product, a person, a stage area, a gate, a supplier. Entity types are registered by an application through the schema extension point. |
| **Relation** | A typed, directed edge between Records and/or Entities (`mentions`, `about`, `caused_by`, `resolves`, `answers`, `supersedes`, `duplicate_of`, `located_at`, ...). Together these form the memory graph. |
| **Principal** | The identity a request is made on behalf of: a user, a group or role they belong to, or the system itself (for internal jobs such as Detectors). Every read is filtered by the Principal's permissions. |
| **ACL** | The list of Principals allowed to read a Record, inherited from its Source. |
| **Citation** | A link from an answer to the exact Record version, and the passage in it, that supports the answer. Every answer Siloless gives has at least one Citation. |

### Tracking

| Term | Meaning |
|---|---|
| **Work Item** | A tracked unit of work of kind `question`, `request`, `incident` or `action`. Has at most one owner, a status, an optional due date, links to evidence, and a full history. |
| **Answer Outcome** | The assessment of a tracked question against memory. One of `answered` (a current authoritative Record answers it), `needs_person` (no answer, or a decision is required; includes a suggested owner) or `conflicting` (Records or people disagree; includes both sides). |
| **Acceptance** | The asker's response to an `answered` outcome. Accepting resolves the question. Declining turns it into an open `needs_person` question. |
| **Conflict Resolution** | For a `conflicting` question, the assignee chooses the correct answer. Siloless records the choice in memory and links the rejected answer with `supersedes`, so the same conflict does not come back. |
| **Claim** | Marking a Work Item as "investigating". The claimant becomes its owner, and everyone else sees that it is being handled. |
| **Response Window** | How long an open, unowned Work Item waits for someone to answer or claim it. When it expires, the Assignment Policy assigns an owner. Configured per channel and kind. |
| **Assignment Policy** | Picks the best candidate owner for a Work Item, using what memory knows about the workers (similar items resolved, related documents owned, role, availability). Falls back to the configured triage owner. |
| **Notification** | An in-app message to a person, role or channel, produced by a Notify node or by Work Item events (assignment, claim, resolution). |

### Monitoring and processes

| Term | Meaning |
|---|---|
| **Signal** | A change that may matter. Kinds: `document_changed`, `communication_event`, `deadline_changed`, `numerical_anomaly`, `operational_event`. |
| **Detector** | A unit that watches Records or streams and emits Signals (diff, threshold, rate-of-change, statistical anomaly, deadline shift, announcement). Built-in ones are configured; custom ones are added through the Detector extension point. |
| **Process** | A user-built graph of Process Nodes that decides what happens to Signals. Stored as configuration (JSON), versioned, and edited in the visual process builder. |
| **Process Node** | One step in a Process. Built-in types: `source`, `lookup`, `condition`, `correlate`, `create_work_item`, `notify`. Each type declares a configuration schema; custom types are added through the Process node extension point. |
| **Process Run** | One execution of a Process for one triggering Signal. Records the path taken and each node's output, so results can be explained. |
| **Incident** | A Work Item of kind `incident`, typically created by a Process from one or more Signals. Carries its evidence and Suggested Actions. |
| **Suggested Action** | A proposed next step attached to a Work Item. Accepting it creates an `action` Work Item or runs an Action Handler. |

### Engine

| Term | Meaning |
|---|---|
| **Event Log** | Append-only log of everything that happens in the engine. Source of the audit trail and of Work Item history. |
| **Component** | An optional, independently enableable feature of the engine (see `product.md` for the list). An organization runs exactly the components it enables, and configures each one. |
| **Plugin** | A convenience bundle of custom code (Entity types, Connectors, Detectors, Process node types, Action Handlers, assignment policy, UI panels) registered through the engine's extension points. A way to extend components, not the only way to build an application. |

## Data flow

```
Source ──► Connector ──► Record (+ACL) ──► Memory (Records, Entities, Relations) ◄─────────┐
                            │                    │                                         │
                            │                    └──► Ask ──► answer (+Citations)           │
                            │                                                              │
                            ├──► question/request detection ──► Work Item + Answer Outcome │
                            │       answered ──► asker accepts ──► resolved ───────────────┤
                            │                └─► asker declines ─┐                         │
                            │       needs_person / conflicting ◄─┘                         │
                            │         ──► claim or auto-assign ──► resolved ───────────────┤
                            │                                                              │
                            └──► Detectors ──► Signals ──► Processes ──► Incidents,        │
                                                           (Process Runs)  Actions,        │
                                                                           Notifications   │
                                                                              │            │
                                                                              └► resolved ─┘
```

Resolved Work Items, with their answers and resolutions, become Records in memory. Every arrow is also written to the Event Log.

## Backend modules (`core/backend/src/siloless/`)

Shared infrastructure (always present):

- `memory/`: Records, Entities, Relations, versioning, search, ACL filtering, authoritative-Record resolution, and cited answer retrieval. Ask and tracking both use it, so neither depends on the other.
- `connectors/`: the `Connector` protocol plus generic connectors (webhook/HTTP push, file import, polling) and the built-in communication channel. Domain connectors live in apps.
- `work/`: Work Items, claims, response windows, assignment policy, status lifecycle, history.
- `notifications/`: in-app notifications.
- `events/`: in-process event bus and the append-only Event Log.

Components (each can be disabled):

- `ask/`: questions to the engine in the communication channel, answered from memory with Citations. Hands questions it cannot answer to `tracking/` when that component is enabled.
- `tracking/`: question and request detection in communication Records, Answer Outcome assessment, Acceptance, conflict detection and Conflict Resolution, response window expiry.
- `monitoring/`: Detectors and Signals.
- `processes/`: Process definitions, the node type registry, validation, and the Process executor.

Wiring:

- `components.py`: the component registry and enable/configure wiring.
- `plugins.py`: the optional `Plugin` protocol for bundling custom code.
- `api/`: FastAPI routers and Pydantic schemas. Thin: no business logic. A disabled component exposes no routes.
- `app.py`: `create_app(settings, plugins=[...])` factory used by every app.

## Customization: configuration first, then extension points

Applications adapt the engine in two layers.

1. **Configuration.** Which components are enabled and how each behaves (connected sources and their permission mapping, authoritative sources, tracked channels and response windows, assignment criteria, watched signals and thresholds, and Processes). This is the primary way to build an application and requires no code.
2. **Extension points.** When configuration cannot express the need, applications supply custom code. Each extension point is a Python `Protocol` with a small surface:
   1. Entity types and relation types (schema registration).
   2. Connectors.
   3. Detectors.
   4. Process node types (a node with a configuration schema and an execute function; it appears in the builder's palette automatically).
   5. Action Handlers (what happens when a Suggested Action is accepted).
   6. Assignment Policy.
   7. Reasoner (optional answer synthesis and question detection, for example an LLM; see below).
   8. UI panels and widgets (Svelte components registered with the app shell).

Custom code is passed explicitly at startup; a Plugin is an optional object that bundles several of these together, for example `create_app(settings, plugins=[FactoryPlugin()])`. No import-time magic, no entry-point scanning. Enabled components and their configuration also come from `settings`, so an application can run on configuration alone with no plugins at all.

## Processes

- A Process is a directed acyclic graph that starts at one or more `source` nodes. Saving a Process validates its structure and every node's configuration against the node type's schema; only valid Processes can be activated.
- The backend owns the node type registry and exposes it through the API. The builder's palette and node configuration forms are generated from it, so a custom node type needs no frontend code.
- Process Runs are deterministic for a given Signal, memory state and clock.

## Invariants

These must hold at all times and each should be covered by property-based tests:

- **Permission safety.** A query on behalf of Principal P never returns a Record whose ACL excludes P, including through search results, answers, Citations, relations, evidence links and Work Item links. Derived objects inherit the most restrictive ACL of their evidence.
- **At most one owner, never forgotten.** A Work Item never has more than one owner. An unowned Work Item is either `awaiting_acceptance` or `open` with a running Response Window; when the window expires it is assigned, falling back to the triage owner if the Assignment Policy finds nobody.
- **One claim wins.** If two people claim the same Work Item, exactly one claim succeeds and the other is told who owns it.
- **Valid lifecycle.** Work Item status follows the allowed transition graph: `awaiting_acceptance → resolved` (asker accepts), `awaiting_acceptance → open` (asker declines), `open → investigating` (claim), `open → assigned` (auto or manual), `open → resolved` (answered directly), `assigned → investigating`, `investigating → blocked/resolved`, `blocked → investigating`, `resolved → reopened`, `reopened → investigating/assigned`. A question with an `answered` outcome starts in `awaiting_acceptance`; every other Work Item starts in `open`. Invalid transitions are rejected.
- **Declining never resolves.** A declined answer always leaves the question `open` with a running Response Window.
- **Cited answers.** Every answer cites at least one Record the asker may read. An `answered` outcome cites at least one current authoritative Record. A `conflicting` outcome cites at least two disagreeing Records or people.
- **Append-only history.** Event Log entries are never updated or deleted. Work Item history is reconstructable from the log.
- **Referential integrity.** Relations only connect nodes that exist.
- **Idempotent ingestion.** Ingesting the same Source item twice does not create duplicates; a changed item creates a new Record version.
- **Valid processes.** Only Processes that pass validation can be activated; an active Process is acyclic and every node's configuration matches its schema.
- **Explainability.** Every Work Item created by a Process links to its triggering Signals and the Process Run that created it.

## Intelligence approach

The default Detectors, question detection, answer retrieval, Answer Outcome assessment and Process nodes are deterministic (retrieval, thresholds, statistics, pattern matching) so behavior is testable and demos run offline. An optional `Reasoner` interface may add LLM-based answer synthesis, question detection or summaries, always with the deterministic path as fallback and with ACL filtering applied before any content leaves the engine.
