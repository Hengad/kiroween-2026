---
inclusion: always
---

# Tech stack and commands

Pick the latest stable version of each tool when scaffolding, then pin it in the lock files. Do not add a new dependency without a clear reason; prefer the standard library and the tools listed here.

## Backend (core and apps)

- Python 3.12+
- FastAPI, Pydantic v2 for API schemas and settings (`pydantic-settings`)
- SQLAlchemy 2.0 (typed ORM) + Alembic migrations
- SQLite by default (with FTS5 for full-text search); the storage layer must stay portable to PostgreSQL
- WebSockets (FastAPI) for live chat messages, Work Item changes, Signals, notifications and simulation updates
- `uv` for environments and dependencies, as a uv workspace (root `pyproject.toml`)
- Testing: `pytest`, `pytest-asyncio`, `httpx` (ASGI test client), `hypothesis` for property-based tests, `pytest-cov`
- Quality: `ruff` (lint + format), `mypy` (strict on `core/`)

## Frontend (core UI library and apps)

- Svelte 5 with runes, TypeScript in strict mode
- `core/frontend`: Svelte component library `@siloless/ui`, built with `svelte-package`
- App frontends: SvelteKit with `adapter-static` (single-page app; FastAPI is the only backend)
- npm workspaces (root `package.json`)
- API types generated from the FastAPI OpenAPI schema with `openapi-typescript`; never hand-write API response types
- Svelte Flow (`@xyflow/svelte`, 1.x, Svelte 5) for the process builder
- Testing: Vitest, `@testing-library/svelte`, Playwright for end-to-end demo flows
- Quality: ESLint, Prettier, `svelte-check`

## Commands (PowerShell, run from the repo root)

These become valid once the scaffold exists. Use one-shot commands; never start watchers or dev servers from the agent.

| Task | Command |
|---|---|
| Install Python deps | `uv sync` |
| Python tests (all) | `uv run pytest` |
| Python tests (core only) | `uv run pytest core/backend` |
| Python lint / format check | `uv run ruff check .` ; `uv run ruff format --check .` |
| Python type check | `uv run mypy core/backend/src` |
| Install JS deps | `npm install` |
| Frontend unit tests | `npm run test --workspaces --if-present -- --run` |
| Frontend type check | `npm run check --workspaces --if-present` |
| Regenerate API types | `npm run gen:api --workspace @siloless/ui` |

Dev servers are started manually by the user, for example:

- Backend: `uv run uvicorn siloless_factory.main:app --reload`
- Frontend: `npm run dev --workspace siloless-factory-frontend`

## Conventions

- Configuration through environment variables and `.env` files loaded by `pydantic-settings`. Secrets never go in code, tests, fixtures or logs. Commit `.env.example`, never `.env`.
- Timestamps are timezone-aware UTC in storage and the API; convert only in the UI.
- IDs are UUIDv7 or ULID strings (sortable).
- Simulations use a seeded random generator and an injectable clock so runs are reproducible.
