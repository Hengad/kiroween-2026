# Requirements Document: Memory and work foundation

## Introduction

This spec builds the shared infrastructure that every Siloless component stands on: permission-aware organizational memory, Work Items with a strict lifecycle and ownership rules, and an append-only Event Log. Nothing here depends on a component being enabled. Question tracking, Ask, change monitoring and the process builder are separate specs that build on this one.

Terms such as Record, Principal, ACL, Work Item and Claim are defined in `.kiro/steering/architecture.md` and are used here with the same meaning.

**In scope:** Principals and permission filtering, Record ingestion and versioning, Entities and Relations, search, the Event Log, Work Items (creation, ownership, claims, lifecycle, history), and the HTTP API for all of these.

**Out of scope (later specs):** question and request detection, Answer Outcomes, Citations and Acceptance (spec 2); Response Window expiry and the Assignment Policy (spec 2); Signals, Detectors and Processes (spec 4); the component registry (introduced with the first component, spec 2); the frontend (spec 3); authentication.

## Assumptions to confirm

- There is no authentication in the hackathon scope. A request names its Principal in a request header, and the API trusts it. The header is the only place that trust is placed.
- Full-text search uses SQLite FTS5. Semantic (embedding) search is not required.

## Requirements

### Requirement 1: Principals and group membership

**User Story:** As an organization, I want every read performed on behalf of an identity with known memberships, so that access to information follows the rules of the source system.

#### Acceptance Criteria

1. THE system SHALL represent a Principal as a user, a group or a role, each with a stable identifier.
2. THE system SHALL store the group and role memberships of each user.
3. WHEN a request is made on behalf of a user, THE system SHALL expand that user to the set containing the user, every group the user belongs to, every role the user holds, and the built-in `everyone` group, to which every user implicitly belongs.
4. WHEN group membership changes, THE system SHALL apply the new memberships to all subsequent reads.
5. THE system SHALL provide a distinct system Principal for internal jobs, and SHALL NOT accept the system Principal from an API request.
6. IF a request names a Principal that does not exist, THEN THE system SHALL reject the request with a stable error code.

### Requirement 2: Ingesting Records

**User Story:** As an integrator, I want to push normalized information from a Source into memory, so that it can be found and related to other information.

#### Acceptance Criteria

1. THE system SHALL accept a Record consisting of a Source identifier, a Source-assigned external identifier, a kind, a title, text content, a metadata object, an ACL, and the time it occurred at the Source.
2. WHEN a Record is ingested, THE system SHALL assign it an identifier, store it, and make it findable by search.
3. WHEN a Record with the same Source identifier and external identifier and identical content is ingested again, THE system SHALL NOT create a new Record or a new version.
4. WHEN a Record with the same Source identifier and external identifier but different content, metadata or ACL is ingested, THE system SHALL store a new version and SHALL leave earlier versions unchanged and readable.
5. THE system SHALL mark exactly one version of each Record as the current version, being the most recently ingested.
6. IF an ingested Record is missing a required field, exceeds the configured size limit, or has an empty ACL, THEN THE system SHALL reject it with a stable error code and SHALL store nothing.
7. THE system SHALL treat Record content as data only, and SHALL NOT interpret or execute it.

### Requirement 3: Authoritative Records

**User Story:** As an organization, I want to say which sources and document types are official, so that later features can tell an official document from a casual message.

#### Acceptance Criteria

1. THE system SHALL read from configuration the list of Source identifiers and Record kinds that count as authoritative.
2. THE system SHALL report a Record version as authoritative only when it is the current version and its Source or kind is configured as authoritative.
3. WHEN a newer version of a Record is ingested, THE system SHALL stop reporting the previous version as authoritative.
4. WHERE no authoritative Sources or kinds are configured, THE system SHALL report no Record as authoritative.

### Requirement 4: Permission-filtered reads

**User Story:** As a user, I want to see only the information the source systems would let me see, so that Siloless never leaks anything.

#### Acceptance Criteria

1. THE system SHALL require a Principal for every operation that reads Records, Entities, Relations or Work Items.
2. WHEN a Principal reads a Record by identifier, THE system SHALL return its current version only if the expanded Principal set intersects that version's ACL.
3. IF a Record exists but the Principal may not read it, THEN THE system SHALL respond exactly as it does for a Record that does not exist.
4. WHEN a Principal searches or lists Records, THE system SHALL apply the ACL filter inside the query, so that every result is readable by that Principal and no result count, snippet or ranking reveals a Record the Principal cannot read.
5. THE system SHALL treat an older Record version as readable by a Principal only if the Principal's expanded set intersects both that version's ACL and the ACL of the Record's current version, so that revoking access at the Source also hides the older versions.
6. WHEN a Principal requests the versions of a Record, or reads a Record version by identifier, THE system SHALL apply the rule in criterion 5 and SHALL return only the versions the Principal may read. THE system SHALL return the versions newest first, with each version marked as the current version or as superseded, so that a client can show the full history with the latest version highlighted.
7. THE system SHALL NOT offer any read operation without a Principal.

### Requirement 5: Search

**User Story:** As a user, I want to search organizational memory by text, so that I can find what the organization already knows.

#### Acceptance Criteria

1. WHEN a Principal submits a text query, THE system SHALL return the readable current Record versions whose title or content match, ranked by relevance.
2. THE system SHALL support restricting a search by Source, kind, time range and Entity.
3. WHEN a query matches nothing the Principal may read, THE system SHALL return an empty result and not an error.
4. THE system SHALL return, for each result, the Record identifier, version, title, a matching passage, and the Source.
5. IF a query is empty or exceeds the configured length, THEN THE system SHALL reject it with a stable error code.

### Requirement 6: Entities and Relations

**User Story:** As an organization, I want information linked to the real-world things it is about, and linked to related information, so that connections are not lost between systems.

#### Acceptance Criteria

1. THE system SHALL store Entities, each with an identifier, an Entity type, a Source-assigned key that is unique within its type, a name and attributes.
2. THE system SHALL allow Entity types and Relation types to be registered at startup, and SHALL reject an Entity or Relation whose type is not registered.
3. THE system SHALL store a Relation as a typed, directed link between two nodes, where a node is a Record version or an Entity.
4. IF a Relation names a node that does not exist, THEN THE system SHALL reject it and store nothing.
5. THE system SHALL make a Relation readable only by a Principal who can read every Record version the Relation connects.
6. WHEN a Principal reads the Relations of a node, THE system SHALL return only the Relations that Principal may read.
7. WHEN a Principal reads an Entity, THE system SHALL return the Records linked to it that the Principal may read, and SHALL omit the others without indicating that they exist.
8. THE system SHALL make Entities, and Relations that connect only Entities, readable by every known Principal.
9. WHEN a Relation with the same type and endpoints already exists, THE system SHALL return the existing Relation and SHALL NOT store a duplicate or append an event.
10. WHEN an Entity with the same type and key is submitted again, THE system SHALL return the existing Entity, and SHALL update its name and attributes and append an event only if they changed.

### Requirement 7: Event Log

**User Story:** As an organization, I want a permanent record of everything that happened, so that nothing is lost and history can be explained.

#### Acceptance Criteria

1. WHEN a Record, Entity, Relation or Work Item is created or changed, THE system SHALL append an event describing the change.
2. THE system SHALL write the event in the same transaction as the change it describes, so that either both exist or neither does.
3. THE system SHALL give each event a unique identifier, a timestamp, an event type, the acting Principal, and a reference to the subject.
4. THE system SHALL NOT provide any operation that updates or deletes an event.
5. THE system SHALL return events in the order they were appended.
6. WHEN a Principal queries events for a subject, THE system SHALL return only events whose subject that Principal may read.

### Requirement 8: Creating Work Items

**User Story:** As a team member, I want questions, requests, incidents and actions tracked as Work Items, so that none of them is forgotten.

#### Acceptance Criteria

1. THE system SHALL create a Work Item with a kind (question, request, incident or action), a title, a description, an optional due date, a list of evidence links to Records, and an initial status.
2. THE system SHALL accept only `open` or `awaiting_acceptance` as an initial status, and SHALL default to `open`.
3. WHEN a Work Item is created without an owner, THE system SHALL leave it without an owner. WHEN a Work Item is created with an owner and no initial status, THE system SHALL set its status to `assigned`. IF a Work Item is created with an owner and an initial status of `awaiting_acceptance`, THEN THE system SHALL reject it.
4. THE system SHALL make a Work Item readable by its creator and its owner, and by any other Principal who can read every evidence Record version the Work Item links to.
5. WHEN a Principal reads a Work Item, THE system SHALL omit evidence links to Record versions that Principal may not read.
6. IF an evidence link names a Record version that does not exist, THEN THE system SHALL reject the Work Item and store nothing.
7. WHERE a Work Item has no evidence, THE system SHALL make it readable only by its creator and its owner.

### Requirement 9: Work Item lifecycle

**User Story:** As a team member, I want every Work Item to move through clear states, so that I always know where it stands.

#### Acceptance Criteria

1. THE system SHALL allow only these status transitions:
   - `awaiting_acceptance` to `resolved` or `open`
   - `open` to `investigating`, `assigned` or `resolved`
   - `assigned` to `investigating`
   - `investigating` to `blocked` or `resolved`
   - `blocked` to `investigating`
   - `resolved` to `reopened`
   - `reopened` to `investigating` or `assigned`
2. IF a requested transition is not in that list, THEN THE system SHALL reject it with a stable error code and SHALL leave the Work Item unchanged.
3. WHEN a Work Item changes status, THE system SHALL record who changed it, when, the old status and the new status.
4. WHEN a Work Item is resolved, THE system SHALL require a resolution text, and SHALL store it with the Work Item.
5. WHEN a Work Item is reopened, THE system SHALL keep its earlier resolution in its history.

### Requirement 10: Ownership and claims

**User Story:** As a team member, I want to mark a question as "investigating" so that nobody else duplicates the work, and I want it to always be clear who is responsible.

#### Acceptance Criteria

1. THE system SHALL allow a Work Item to have at most one owner at any time.
2. WHEN a Principal who can read an `open` Work Item claims it, THE system SHALL make that Principal the owner and set the status to `investigating`.
3. IF a Work Item already has an owner when a claim arrives, THEN THE system SHALL reject the claim, SHALL leave the Work Item unchanged, and SHALL tell the claimant who the owner is.
4. WHEN two or more claims for the same unowned Work Item arrive at the same time, THE system SHALL accept exactly one and reject the others.
5. WHEN a Principal who can read a Work Item reassigns it to another user, THE system SHALL replace the owner with that user and SHALL record the previous owner in the Work Item's history.
6. THE system SHALL allow only users, and not groups, roles or the system Principal, to be owners, except for an assignment made by the system Principal in a later spec.
7. WHEN a Work Item is assigned an owner, THE system SHALL change only its owner and, where the transition graph requires it (`open` or `reopened` to `assigned`), its status. THE system SHALL reject reassignment of a Work Item in `awaiting_acceptance` or `resolved`.

### Requirement 11: Work Item history and queries

**User Story:** As a team member, I want to see everything that happened to a Work Item, and to find the Work Items that matter to me.

#### Acceptance Criteria

1. THE system SHALL return the history of a Work Item as the ordered list of its events from the Event Log.
2. FOR ANY Work Item, replaying its events from the Event Log SHALL produce its current status, owner and resolution.
3. WHEN a Principal lists Work Items, THE system SHALL return only those the Principal may read, and SHALL support filtering by kind, status and owner.
4. THE system SHALL return Work Items in a stable order, newest first by default.

### Requirement 12: HTTP API

**User Story:** As a frontend or integration developer, I want one consistent, documented API for memory and work, so that I can build on it without reading the code.

#### Acceptance Criteria

1. THE system SHALL expose endpoints for ingesting Records, reading Records and their versions, searching, creating and reading Entities and Relations, creating, listing, reading, claiming, reassigning and transitioning Work Items, creating and listing Principals, setting a user's group and role memberships, and querying events.
2. THE system SHALL identify the Principal of each request from a request header.
3. THE system SHALL publish an OpenAPI description from which the frontend generates its types.
4. WHEN a request fails, THE system SHALL respond in the problem-details format with a stable machine-readable error code.
5. THE system SHALL keep routing and schema mapping in the API layer and SHALL keep business rules in the domain modules, so that every rule above is testable without HTTP.
6. THE system SHALL persist all data in SQLite, and SHALL support an in-memory database for tests.

## Property-based tests

These requirements are invariants and are covered by Hypothesis tests in addition to example-based tests:

| Property | Requirements |
|---|---|
| For any Records, ACLs, memberships and Principal, search, list, get, versions, Relations, Entity links, events and Work Items return only what the Principal may read, including after access to a Record is tightened in a later version | 4, 5, 6, 7, 8 |
| Ingesting the same item twice never creates a duplicate; a changed item always creates exactly one new version | 2 |
| At most one version of a Record is current, and at most one is authoritative | 2, 3 |
| Relations never connect missing nodes | 6 |
| Any sequence of transitions is accepted only if every step is in the allowed graph (stateful test) | 9 |
| A Work Item never has more than one owner; of N concurrent claims exactly one wins | 10 |
| Replaying a Work Item's events reproduces its current state | 11 |
| Events are never modified or removed by any operation | 7 |

## Decisions

Answers to review questions. The demo has one real user, the judge, so access rules stay simple.

- A Work Item's creator and owner can always read it (8.4, 8.7).
- Anyone who can read a Work Item can reassign it (10.5). There is no role restriction.
- A built-in `everyone` group, which every user belongs to, is how a Record is made public (1.3). An empty ACL is still rejected (2.6).
- A derived object (Relation, Work Item) is readable by a Principal who can read every Record version it derives from. This replaces an earlier "intersection of ACLs" wording, which is wrong when ACLs name different groups that overlap in membership.
- The current version's ACL governs older versions too (4.5). If the Source tightens access, people who lost access cannot read old versions, and cannot read Work Items or Relations built on them.