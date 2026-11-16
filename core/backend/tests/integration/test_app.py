import httpx

from siloless.app import create_app
from siloless.settings import Settings


async def test_health_endpoint_reports_ok() -> None:
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
