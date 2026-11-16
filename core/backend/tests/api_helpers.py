"""Helpers for tests that drive the HTTP API."""

from typing import Any

from fastapi.testclient import TestClient

HEADER = "X-Principal-Id"


def as_user(user: str) -> dict[str, str]:
    return {HEADER: user}


def record_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source_id": "wiki",
        "external_id": "press-3-seal",
        "kind": "procedure",
        "title": "Press 3 seal replacement",
        "content": "Replace the hydraulic seal every 500 hours.",
        "metadata": {},
        "acl": ["group:maintenance"],
        "occurred_at": "2026-11-01T08:00:00Z",
    }
    body.update(overrides)
    return body


def seed_people(client: TestClient) -> None:
    """anna and cy are in group:maintenance, bo is in group:sales."""
    for principal in [
        "group:maintenance",
        "group:sales",
        "user:anna",
        "user:bo",
        "user:cy",
    ]:
        response = client.put(f"/principals/{principal}", json={"name": principal.split(":")[1]})
        assert response.status_code == 200, response.text
    for user, groups in [
        ("user:anna", ["group:maintenance"]),
        ("user:bo", ["group:sales"]),
        ("user:cy", ["group:maintenance"]),
    ]:
        assert (
            client.put(f"/users/{user}/memberships", json={"memberships": groups}).status_code
            == 200
        )


def ingest_record(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/ingest/records", json=record_body(**overrides))
    assert response.status_code in (200, 201), response.text
    result: dict[str, Any] = response.json()
    return result
