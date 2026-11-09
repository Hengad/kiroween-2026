# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).
Entries are prefixed with their scope: `core:`, `factory:`, `festival:`, `repo:` or `kiro:`.

## [Unreleased]

### Added

- kiro: Steering files for product vision, engine architecture and domain language, tech stack, repository structure, TDD workflow, project memory, and file-scoped conventions for Python, Svelte and simulations.
- kiro: Hooks that remind the agent to write tests first and to update README and CHANGELOG when a spec task completes.
- repo: README, CHANGELOG, MIT license and `.gitignore` (`.kiro/` stays committed, as the hackathon rules require).
- kiro: Decided that README.md and CHANGELOG.md are pulled into every Kiro task through `project-memory.md` file references, so earlier decisions are always in context.
- kiro: Decided on deterministic Detectors and Rules by default, with an optional LLM `Reasoner` behind an interface, so demos and tests run offline.
- kiro: Decided that simulations act as external Sources and feed the engine only through connectors, so they can be swapped for real systems.

### Changed

- kiro: Reframed the engine as a set of optional, configurable **components** (features) rather than something extended only by plugins. The three pillars are goals, not components; components are concrete features introduced over time. Updated `product.md`, `architecture.md` and `README.md`. Customization is now "configuration first, then extension points," with plugins as an optional way to bundle custom code. The concrete component list is deliberately left open.
- repo: Restructured the demo apps to share the core backend. Apps are no longer "backend/simulation/frontend" triplets; instead they are "config/simulation/frontend" with a `main.py` that starts the shared core backend. Each app defines which components to enable and their configuration in `config.yaml`, optionally providing custom code through the Plugin mechanism. Updated `structure.md`, `README.md` and the repository layout.
- kiro: Manual editing and refinement of the files by Henry. Aligning the text more into my vision of the engine / code template.
- kiro: Defined the first four components in `product.md`: Ask, Question and request tracking, Change monitoring, and Process builder (Svelte Flow). Recorded the demo layout (simulation left, engine right; Chat and Tracked questions views) and the decisions on hackathon scope.
- kiro: Replaced Rules and Insights with Processes and incidents in `architecture.md`. Processes are user-built node graphs stored as configuration; incidents are Work Items. Added terms for Answer Outcome, Acceptance, Conflict Resolution, Claim, Response Window and Citation.
- kiro: Changed the "single owner" invariant to "at most one owner, never forgotten", because tracked questions start unowned and are auto-assigned only after their response window expires. Added the `awaiting_acceptance` status for answers the asker has not yet accepted.
- kiro: Updated `frontend.md`, `structure.md`, `tech.md`, `tdd.md`, `simulations.md` and `README.md` to match. Added `@xyflow/svelte` to the stack.
