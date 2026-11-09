---
inclusion: fileMatch
fileMatchPattern: '**/*.py'
---

# Python backend conventions

- Full type hints everywhere; `core/` passes `mypy --strict`. Use `Protocol` for extension points and `dataclass(frozen=True)` or Pydantic models for value objects.
- Separate three kinds of model: SQLAlchemy ORM models (storage), domain objects (logic), Pydantic schemas (API). Map between them explicitly at the edges.
- Dependencies are injected: clock, ID generator, random generator, repositories and the event bus come in through constructors or FastAPI dependencies. No module-level singletons holding state.
- Every repository read method takes the requesting `Principal` and applies ACL filtering in the query itself. There is no "unfiltered" read in the public API; internal system reads use an explicit system principal.
- Write to the Event Log in the same transaction as the state change it describes.
- Async for I/O (API handlers, connectors, WebSockets). Keep pure domain logic synchronous and side-effect free so it is easy to test.
- Routers stay thin: validate input with Pydantic, call a service, map the result to a schema. Return problem-detail style errors with stable error codes.
- Use parameterized queries only (SQLAlchemy expressions or bound parameters). Never format SQL strings with user input.
- Treat all ingested content (emails, documents, web pages, sensor payloads) as untrusted data: validate at the connector boundary, cap sizes, and never execute or evaluate it.
- Logging via the standard `logging` module with structured context. Never log secrets or full record contents.
- Plugins register through `create_app(settings, plugins=[...])`. A plugin must be loadable in tests without starting servers or simulations.
