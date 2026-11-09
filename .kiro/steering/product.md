---
inclusion: always
---

# Product: Siloless

Siloless is a lean, reusable engine (a "skeleton" code template) that unifies information silos, communication silos, and resulting disjointed actions in organizations. It is built from independent **components** (features) that an organization chooses to use or not, and each component is configurable to fit that organization. Concrete applications are built on top of it by selecting components and configuring them, and optionally extending them with custom code; never by forking the core.

## Problem

Organizations lose information between tools and teams. Emails, documents, tickets, inventory, schedules, sensor data and past incidents live in separate systems. Nobody sees how they relate, signals get missed, and questions and actions are forgotten because nobody owns them.

## Consequences of the problem

- **Delayed decisions and responses.** People spend time searching for information, contacting colleagues, and reconstructing what happened before they can act.
- **Unclear ownership.** Questions and requests get passed between departments, teams or other groups of people without a clear owner, deadline, or confirmation that the issue has been resolved.
- **Duplicated work and wasted resources.** Multiple people investigate the same issue, recreate the same analysis, request the same data, or perform work that another team has already completed.
- **Reduced productivity and financial losses.** As a result of the above.

## The three pillars

These are what Siloless is about: the goals the engine exists to serve. They are not the components; a component is a concrete feature that contributes to one or more of these pillars.

**1. Non-fragmented organizational memory.**
Connect emails, documents, management tools, inventory, schedules, websites, data history and resolved incidents. Create internal relations between different kinds of information. Respect the access permissions of each source: a user only ever sees what the source system would let them see.

*Hackathon scope:* A seeded dataset with versioned documents and linked entities, plus basic source-backed retrieval. No need for a general-purpose knowledge graph.

**2. Context and intelligence.**
Monitor document changes, communications, numerical anomalies, operational alerts and events (for example a sensor fault or an unavailable external service) and deadline changes. Combine these signals with the memory graph to produce meaningful alerts and suggested actions. Configurable rules correlate related events and identify consequential changes.

*Hackathon scope:* Four input types, entity matching, simple thresholds, time-window correlation and duplicate suppression. No universal AI reasoning engine.

**3. Tracking and accountability.**
No question, incident or action is lost. Every work item ends up with exactly one assignee who is responsible for completing it: whoever claims it, or the best candidate once its response window runs out. Work items, including resolved ones, are stored permanently and become part of the organizational memory.

*Hackathon scope:* Automatic creation, suggested ownership, manual reassignment, status transitions, in-app notifications and resolution records.

## Components

The first components are listed below. More will be added by the user over time; record each new one here. Each component is opt-in and configurable (see "Customization" below).

### Ask the engine before asking people

Anyone can ask Siloless a question: about already answered questions, how past incidents were resolved, standard procedures, and so on. Answers come from organizational memory and cite the Records they are based on.

Ask works inside the communication channel. The engine replies in the chat when it can answer. When it cannot, and Question and request tracking is enabled, the question becomes a tracked open question.

Configurable: which Sources and document types count as authoritative, how recent a Record must be to count as current, and citation and answer formatting.

### Question and request tracking

Siloless detects questions and requests in communication channels and tracks each one as a Work Item.

Every question is assessed into one of three outcomes:

- **Already answered.** A current, authoritative Record answers it. The reply cites the exact Records it is based on. The asker accepts or declines the answer. An accepted answer resolves the question. A declined answer turns it into an open question that needs a person.
- **Needs a person.** No answer is available, or the question requires a decision. Siloless suggests an appropriate owner.
- **Potentially conflicting.** Two Records or people give different answers. Siloless flags the discrepancy, shows both sides, and does not guess. The assignee must choose which answer is correct, and this gets updated in organizational memory.

If the question is in "needs a person" or "potentially conflicting" state:

- Anyone can mark a question or request as **investigating**. This makes them its owner and shows everyone else that it is being handled, so nobody duplicates the work.
- If nobody answers or claims it within its **response window**, Siloless auto-assigns it to the best candidate, using what it knows about the workers: who resolved similar items, who owns the related documents, role and availability.
- When it is resolved, the question, its answer and its resolution move into organizational memory.

Configurable: which channels are tracked, response windows per channel or kind, assignment criteria and their weights, and the fallback triage owner.

*Hackathon scope:* One communication channel, built into the engine frontend. Messages come from the user and from the simulation. The same channel is used to ask the engine: it replies if it can, and creates a tracked open question if it can't. No email, Teams or Slack integration. "Investigating" claims do not expire.

### Change monitoring

Siloless watches organizational memory for changes and turns them into incidents and potential actions. The Signal kinds are:

- document change
- communication event (for example an announcement)
- deadline change
- numerical anomaly
- operational event (for example a sensor fault or an unavailable external service)

Configurable: which Sources and Entities are watched, thresholds and severities, and which Processes handle each Signal kind.

*Hackathon scope:* Four Signal kinds, chosen from the list above once the simulations are defined.

### Process builder

Users build the processes that decide what happens to Signals, using a visual flowchart editor (Svelte Flow). The node types are:

| Node | What it does |
|---|---|
| Source | Starts the process when a matching Signal arrives (by kind, Source or Entity). |
| Lookup | Pulls context and similar past cases from organizational memory. |
| Condition | Branches on Signal fields, thresholds or Lookup results. |
| Correlate | Combines related Signals, for example on the same Entity within a time window, and suppresses duplicates. |
| Create work item | Creates an incident, action, question or request with an owner and suggested actions. |
| Notify | Sends an in-app notification to a person, role or channel. |

Processes are stored as configuration, so building one requires no code. The demos ship with default processes that the user (a judge or the developer) can edit, or replace with their own.

## Customization

This is the heart of the product, and what the two demo apps must prove.

- **Components are opt-in.** An organization enables the components it wants and the engine runs with exactly that set. The engine never assumes a component that is switched off is present, and a component does not hard-require another to run (it may do more when a companion component is also enabled). Organizational memory, Work Items and the Event Log are shared infrastructure, not components; they are always present.
- **Each component is configurable.** Behavior is driven by the organization's configuration, not by code changes. Each component above lists its configurable surface.
- **Extension is optional and layered.** Most adaptation is configuration. When an organization needs behavior the configuration cannot express, it provides custom code (for example a connector, detector, process node type, action handler, assignment policy or UI panel) through the engine's extension points. Plugins are a convenience for bundling such custom code; they are one way to extend a component, not the required way to build an application.
- **Sensible defaults.** Every component ships working defaults so a bare configuration runs. Customization overrides defaults rather than starting from nothing.

## Deliverables

| Folder | What it is |
|---|---|
| `core/` | The Siloless engine: FastAPI backend package and Svelte UI library. Domain-agnostic, component-based. |
| `siloless-factory/` | Demo app 1: engine frontend + a simulated multi-stage manufacturing line. |
| `siloless-festival/` | Demo app 2: engine frontend + a crowd simulation for a festival. |

The two demos are distinct not only in domain but in how they compose and configure the engine: they enable different components and configure the shared ones differently, which is what demonstrates the template's versatility. Details of both simulations will be supplied by the user later. Do not invent detailed simulation requirements; ask, or leave a clearly marked TODO.

### Demo layout

Each demo is a split screen: the simulation on the left, the engine frontend on the right. The engine frontend supports every component listed above. For communication it has two views:

- **Chat.** The communication channel. The user and simulated workers post messages here, and the engine replies when it can answer.
- **Tracked questions.** Questions and requests the engine is tracking, with their outcome, owner and status. This is where the user claims ("investigating"), answers, accepts or declines answers, and resolves conflicts.

The user always posts as a single person, shown as "You". Simulated workers are the other people in the organization and are the candidates for auto-assignment.

## Decisions

Answers to earlier open questions. Follow these unless the user changes them.

- Only the built-in communication channel is in hackathon scope. Messages come from the user and the simulation; there is no email, Teams or Slack integration.
- An `answered` question resolves only when the asker accepts the answer. A declined answer turns it into an open question.
- "Investigating" claims do not expire in the demo.
- Ask is used from the chat. The engine replies there when it can; otherwise the question becomes a tracked open question.
- The demo user is a single persona, "You". There is no persona switcher.

## Open questions

Decisions still needed from the user. Do not resolve these by assumption; ask when a task depends on one.

- Which four Signal kinds are in hackathon scope? This depends on the simulations.

## Hackathon context

- Built for Kiroween 2026 (https://kiroween.devpost.com/), category **Skeleton Crew**: a skeleton template lean enough to be clear but flexible enough to support various use cases, demonstrated with two distinct applications.
- Submission deadline: Friday, December 4, 2026, 2:00 PM Pacific Time.
- Repository requirements:
  - Public GitHub repo with an open source license file (`LICENSE`, MIT) at the root.
  - The `/.kiro` directory (specs, hooks, steering) must be committed. Never add `.kiro` or its sub-folders to `.gitignore`.
  - The two applications must live in two separate top-level folders (`siloless-factory/`, `siloless-festival/`).
  - All source, assets and instructions needed to run the project must be in the repo.
- Judging rewards real impact, thorough use of Kiro (specs, hooks, steering, property-based testing, MCP), polished design and a clear demo. Keep the Kiro usage visible and intentional.

## Product principles

- **Lean, composable core.** The core is a set of independent components with clean seams. If a feature only makes sense for one domain, it belongs in that application's configuration or custom code, not in `core/`.
- **Configuration before code.** Prefer making behavior configurable over making it hard-coded. Reach for custom code only when configuration genuinely cannot express the need.
- **Versatility is proven, not claimed.** Each component and each extension point must be exercised by at least one demo app, and the two demos must differ in which components they use and how they configure them.
- **Permissions are never an afterthought.** Access control is enforced in the backend query layer, not only in the UI.
- **Explainable intelligence.** Every answer, incident or suggested action shows the evidence (Signals, Records, Relations, Process runs) that produced it.
- **Nothing falls through the cracks.** An unassigned work item should be force-assigned to the best candidate (infered from organizational memory) once its response window expires. It can be reassigned if needed.
- **Runs offline.** Demos and tests must work without paid external services. Optional integrations (for example an LLM provider) sit behind interfaces with a deterministic default.
