"""Application factory used by every Siloless app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from siloless.api.errors import install_error_handlers
from siloless.api.routes import (
    events,
    graph,
    ingest,
    principals,
    records,
    search,
    work_items,
)
from siloless.api.schemas import ProblemDetails
from siloless.container import build_container
from siloless.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    container = build_container(settings if settings is not None else Settings())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        container.db.dispose()

    app = FastAPI(
        title="Siloless",
        lifespan=lifespan,
        responses={"default": {"model": ProblemDetails, "description": "Error (problem details)"}},
    )
    app.state.container = container
    install_error_handlers(app)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in (
        principals.router,
        ingest.router,
        records.router,
        search.router,
        graph.router,
        work_items.router,
        events.router,
    ):
        app.include_router(router)

    return app
