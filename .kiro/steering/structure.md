---
inclusion: always
---

# Repository structure

Target layout. Create folders only when the first file that needs them is written.

```
siloless/
├── .kiro/                      # steering, specs, hooks (always committed)
├── core/                       # the Siloless engine (shared by all apps)
│   ├── backend/
│   │   ├── pyproject.toml      # package: siloless
│   │   ├── src/siloless/       # memory/ connectors/ work/ notifications/ events/ ask/ tracking/ monitoring/ processes/ api/ components.py plugins.py app.py
│   │   └── tests/              # unit/ integration/ properties/
│   └── frontend/
│       ├── package.json        # package: @siloless/ui
│       └── src/lib/            # app shell, chat, tracked questions, work item board, process builder, notifications, memory explorer
├── siloless-factory/           # demo app 1
│   ├── config.yaml             # engine configuration: enabled components, connectors, detectors, processes, assignment
│   ├── simulation/             # package: factory_sim (multi-stage manufacturing line)
│   ├── frontend/               # SvelteKit app using @siloless/ui
│   ├── main.py                 # startup: load config, run core backend
│   └── README.md
├── siloless-festival/          # demo app 2
│   ├── config.yaml             # engine configuration for this app
│   ├── simulation/             # package: festival_sim (crowd simulation)
│   ├── frontend/               # SvelteKit app using @siloless/ui
│   ├── main.py                 # startup: load config, run core backend
│   └── README.md
├── pyproject.toml              # uv workspace root (siloless package)
├── package.json                # npm workspaces root (@siloless/ui package)
├── README.md
├── CHANGELOG.md
└── LICENSE
```

## Dependency rules

- `core/` never imports from, or mentions, `siloless-factory/` or `siloless-festival/`. Factory or festival vocabulary (machine, stage, crowd, gate) in `core/` is a design smell; generalize it or move it to the app's config or custom extensions.
- Apps depend on `core/` only through its public API: the `siloless` package exports and `@siloless/ui` exports. Apps load the core backend with their `config.yaml` and optionally pass custom code (Connectors, Detectors, Process node types, etc.) via the Plugin mechanism.
- The two apps never import from each other. Shared needs get promoted to `core/` configuration or extension points.
- A simulation is an external "world". It feeds the app only through the same interfaces a real Source would use (connector ingestion API, webhooks, files). The app backend does not import the simulation package; the simulation does not write to the engine database.
- `api/` modules contain routing and schema mapping only. Business logic lives in the domain modules and is testable without HTTP.

## Naming

- Python: packages and modules `snake_case`, classes `PascalCase`, protocols named after the role (`Connector`, `Detector`, `ProcessNodeType`).
- Svelte components `PascalCase.svelte`; stores and utilities `camelCase.ts`.
- Tests mirror source paths: `src/siloless/work/assignment.py` → `tests/unit/work/test_assignment.py`.
- Property-based tests go in `tests/properties/` and are named after the invariant: `test_permission_safety.py`.

## Apps share the core backend

Each demo app (`siloless-factory/`, `siloless-festival/`) is a complete deployment (config, frontend, simulation) but does not implement a backend. Instead, it:
1. Defines which components to enable and how to configure them in `config.yaml`.
2. Optionally provides custom code (domain-specific Connectors, Detectors, Process node types, etc.) that the core backend loads at startup via the Plugin mechanism.
3. Runs `main.py` to start the shared core backend with the app's configuration.

This structure proves the template's versatility: two distinct domains run on the same engine with different configurations and optional extensions.
