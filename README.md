# Siloless

Siloless is a lean engine for unifying information silos, communication silos, and resulting disjointed actions in organizations. It connects scattered sources into one permission-aware memory, turns changes and anomalies into explained alerts, and makes sure every question, incident and action has an owner.

It is built as a **skeleton code template**: the domain-agnostic core is a set of independent components (features) that you switch on or off and configure for your organization. You build an application by selecting components and configuring them, and extending them with custom code only when configuration is not enough. Two demo applications show this:

- **siloless-factory**: Siloless for a multi-stage manufacturing line, driven by a production simulation.
- **siloless-festival**: Siloless for a music festival, driven by a crowd simulation.

Built for [Kiroween 2026](https://kiroween.devpost.com/), category *Skeleton Crew*.

## What the engine is about

Siloless serves three pillars. These are goals, not the components; components are concrete features (introduced over time) that contribute to one or more pillar.

1. **Organizational memory without silos.** Connectors bring in emails, documents, management tools, inventory, schedules, websites, data history and resolved incidents as Records. The engine links them to each other and to real-world Entities in a memory graph. Each Record keeps the access permissions of its source, and every query is filtered by them.
2. **Context and intelligence.** Detectors watch for document changes, communication events, numerical anomalies, operational events (for example a sensor fault or an unavailable external service) and deadline changes. Processes combine these Signals with the memory graph into incidents that show their evidence and suggest next actions.
3. **Tracking and accountability.** Questions, requests, incidents and actions become Work Items. Each one ends up with exactly one owner: whoever claims it, or the best candidate once its response window runs out. Resolved items stay in memory, so similar future problems can draw on how earlier ones were solved.

## Components

The engine is a set of **components** (features). You enable the ones you want, and the engine runs with exactly that set. Each component is configurable, so most adaptation is a matter of configuration rather than code. The first components are:

| Component | What it does |
|---|---|
| **Ask** | Ask the engine before asking people. Questions in the chat are answered from organizational memory, with citations. Questions it cannot answer become tracked questions. |
| **Question and request tracking** | Detects questions and requests in the chat and tracks each one. Every question gets one of three outcomes: already answered (the asker accepts or declines the cited answer), needs a person, or potentially conflicting. Anyone can mark a question as "investigating" so nobody duplicates the work. Unclaimed questions are auto-assigned to the best candidate when their response window expires. |
| **Change monitoring** | Turns document changes, communication events, deadline changes, numerical anomalies and operational events into Signals. |
| **Process builder** | A visual flowchart editor (Svelte Flow) for the processes that turn Signals into incidents, actions and notifications. Node types: Source, Lookup, Condition, Correlate, Create work item, Notify. |

When configuration is not enough, you extend a component through its extension points (see below); bundling such custom code as a plugin is one convenient option, not a requirement.

```
Source ─► Connector ─► Record (+ACL) ─► Memory ─► Ask ─► cited answer
                          │
                          ├─► question detection ─► tracked question ─► accept / claim / auto-assign ─► resolved ─► Memory
                          │
                          └─► Detectors ─► Signals ─► Processes ─► incidents, actions, notifications ─► resolved ─► Memory
```

## Demo layout

Each demo is a split screen: the simulation on the left, the engine frontend on the right. The engine frontend has a Chat view, where you and the simulated workers post messages and the engine replies, and a Tracked questions view, where questions are claimed, answered and resolved. It also includes the incident board and the process builder.

## Extension points

When configuration is not enough, components are extended through these:

| Extension point | Factory example | Festival example |
|---|---|---|
| Entity and relation types | machine, stage, batch | stage area, gate, zone |
| Connectors | line sensors, maintenance log | gate counters, staff radio log |
| Detectors | throughput drop, sensor fault | crowd density threshold |
| Process node types | fault + upcoming delivery deadline | density rising + next act starting |
| Action Handlers | schedule maintenance | open overflow gate |
| Assignment policy | by line and shift | by zone and duty roster |
| UI panels | live production line view | live crowd map |

These examples illustrate the intent. The simulation details are still to be specified.

## Repository layout

```
core/                 Siloless engine (shared backend + UI library)
  backend/            Python package `siloless` (FastAPI)
  frontend/           Svelte library `@siloless/ui`
siloless-factory/     Demo app 1: config, simulation, frontend
siloless-festival/    Demo app 2: config, simulation, frontend
.kiro/                Kiro steering, specs and hooks
```

## Tech stack

- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, SQLite (FTS5), managed with `uv`
- Frontend: Svelte 5, SvelteKit (static SPA), TypeScript, npm workspaces
- Testing: pytest, Hypothesis (property-based tests), Vitest, Testing Library, Playwright

## Getting started

> Not runnable yet. The commands below are the planned workflow and will work once the scaffold exists.

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js LTS.

```powershell
uv sync
npm install
uv run pytest
npm run test --workspaces --if-present -- --run
```

Run a demo app (two terminals):

```powershell
# Terminal 1: Start the engine with the app's config
uv run python siloless_factory/main.py

# Terminal 2: Start the app's frontend
npm run dev --workspace siloless-factory-frontend
```

Each app (`siloless-factory/`, `siloless-festival/`) has its own configuration (which components to enable, how to configure them) and optional custom code, but shares the core backend engine.

## Development workflow

- **Test-driven.** Every behavior starts as a failing test. Property-based tests cover the engine's invariants (permission safety, at most one owner per Work Item, one claim wins, valid lifecycle, cited answers, append-only history, idempotent ingestion, valid processes).
- **Spec-driven.** Larger features are planned as Kiro specs in `.kiro/specs/` (requirements, design, tasks) before implementation.
- **Steering.** `.kiro/steering/` holds the product, architecture, tech, structure and TDD guidance that Kiro follows. This README and `CHANGELOG.md` are included in Kiro's context on every task, so they serve as the project's memory.
- **Hooks.** `.kiro/hooks/` automates reminders for the test-first rule and for keeping this README and the changelog current.

## Status

| Part | Status |
|---|---|
| Steering, README, changelog, hooks | Done |
| Core engine backend | Not started |
| Core UI library | Not started |
| siloless-factory | Not started; simulation details pending |
| siloless-festival | Not started; simulation details pending |

## License

[MIT](LICENSE)
