from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from siloless.app import create_app
from siloless.settings import Settings


@pytest.fixture
def api() -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        authoritative_sources=["wiki"],
        entity_types=["machine"],
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
