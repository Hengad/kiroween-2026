---
inclusion: always
---

# Test-driven development

All production code in this repo is written test-first. This applies to the core engine, the app plugins, the simulations and the frontend.

## The cycle

1. **Red.** Write the smallest test that expresses the next piece of required behavior. Run it and confirm it fails for the expected reason (not an import error or typo).
2. **Green.** Write the minimum production code that makes it pass. Run the relevant tests.
3. **Refactor.** Clean up code and tests with all tests green. Run the full suite of the affected package.

Repeat in small steps. When reporting progress, state which tests were added and show that they failed before and pass after.

## Rules

- No production code without a failing test that requires it. Pure configuration, docs and type-only changes are exempt.
- A bug fix starts with a test that reproduces the bug.
- Never weaken, skip or delete a test to make the suite pass. If a test is wrong, explain why before changing it.
- Tests describe behavior, not implementation. Name them as sentences: `test_unassigned_work_item_goes_to_triage_owner`.
- Each test arranges its own data. No dependence on test order or on shared mutable state.
- Tests are deterministic: inject clocks and seeded random generators; no real network calls; no sleeping.
- Keep the suite fast. Unit tests use in-memory SQLite or fakes; integration tests use a temporary SQLite file.

## Test layers

| Layer | Where | What |
|---|---|---|
| Unit | `tests/unit/` | Domain logic in isolation (assignment policy, lifecycle, answer outcomes, detectors, process nodes, ACL filter). Most tests live here. |
| Property-based | `tests/properties/` | The invariants listed in `architecture.md`, using Hypothesis. Required for every invariant. |
| Integration | `tests/integration/` | API endpoints via the ASGI client, storage, connector ingestion, plugin registration. |
| Contract | each app's `backend/tests/` | Each app plugin is loaded into `create_app` and exercised through the public API. |
| Frontend component | next to components, `*.test.ts` | Svelte components with Testing Library: render, interact, assert on visible output. |
| End-to-end | each app's `frontend/e2e/` | A few Playwright flows that mirror the demo video script. |

## Property-based testing guidance

- Write Hypothesis strategies for the core domain objects (Principals, ACLs, Records, Relations, Work Items) once, in `core/backend/tests/strategies.py`, and reuse them.
- Prefer properties of the form "for any generated input, invariant X holds", for example: for any set of Records with random ACLs and any Principal, search results are a subset of what that Principal may read.
- Use stateful testing (`RuleBasedStateMachine`) for the Work Item lifecycle and ingestion idempotency.
- When Hypothesis finds a failure, keep the minimal example as an explicit regression test.

## Definition of done for a feature or spec task

- Tests written first and passing, including property tests for any touched invariant.
- `ruff`, `mypy` and `svelte-check` clean for the affected packages.
- Project memory updated: see `project-memory.md` for `CHANGELOG.md` and `README.md` rules.
