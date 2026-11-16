from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from siloless.app import create_app
from siloless.settings import Settings

HEADER = "X-Principal-Id"


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(_env_file=None, database_url="sqlite://", authoritative_sources=["wiki"])
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def as_user(user: str) -> dict[str, str]:
    return {HEADER: user}


def record_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source_id": "wiki",
        "external_id": "press-3-seal",
        "kind": "procedure",
        "title": "Press 3 seal replacement",
        "content": "Replace the hydraulic seal every 500 hours.",
        "metadata": {"owner": "maintenance"},
        "acl": ["group:maintenance"],
        "occurred_at": "2026-11-01T08:00:00Z",
    }
    body.update(overrides)
    return body


def seed_people(client: TestClient) -> None:
    for principal, name in [
        ("group:maintenance", "Maintenance"),
        ("group:sales", "Sales"),
        ("user:anna", "Anna"),
        ("user:bo", "Bo"),
    ]:
        assert client.put(f"/principals/{principal}", json={"name": name}).status_code == 200
    client.put("/users/user:anna/memberships", json={"memberships": ["group:maintenance"]})
    client.put("/users/user:bo/memberships", json={"memberships": ["group:sales"]})


def ingest(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/ingest/records", json=record_body(**overrides))
    assert response.status_code in (200, 201), response.text
    result: dict[str, Any] = response.json()
    return result


# -- principals ---------------------------------------------------------------------


def test_principals_can_be_created_listed_and_given_memberships(client: TestClient) -> None:
    seed_people(client)

    listed = {p["id"]: p for p in client.get("/principals").json()}

    assert listed["user:anna"] == {"id": "user:anna", "type": "user", "name": "Anna"}
    assert "group:everyone" in listed
    response = client.put("/users/user:anna/memberships", json={"memberships": ["group:sales"]})
    assert response.status_code == 200


def test_a_malformed_principal_id_is_rejected(client: TestClient) -> None:
    response = client.put("/principals/anna", json={"name": "Anna"})

    assert response.status_code == 422
    assert response.json()["code"] == "principal_invalid"


def test_memberships_for_an_unknown_user_are_rejected(client: TestClient) -> None:
    response = client.put("/users/user:ghost/memberships", json={"memberships": []})

    assert response.status_code == 422
    assert response.json()["code"] == "principal_unknown"


# -- the principal header -----------------------------------------------------------


def test_reads_need_a_principal_header(client: TestClient) -> None:
    response = client.get("/records/anything")

    assert response.status_code == 400
    assert response.json()["code"] == "principal_required"


def test_an_unknown_principal_is_rejected(client: TestClient) -> None:
    response = client.get("/records/anything", headers=as_user("user:ghost"))

    assert response.status_code == 403
    assert response.json()["code"] == "principal_unknown"


def test_the_system_principal_cannot_be_named_in_a_request(client: TestClient) -> None:
    response = client.get("/records/anything", headers=as_user("system"))

    assert response.status_code == 403
    assert response.json()["code"] == "principal_forbidden"


# -- ingestion ----------------------------------------------------------------------


def test_ingestion_creates_then_ignores_repeats_then_versions_changes(
    client: TestClient,
) -> None:
    first = client.post("/ingest/records", json=record_body())
    again = client.post("/ingest/records", json=record_body())
    changed = client.post(
        "/ingest/records", json=record_body(content="Replace the seal every 400 hours.")
    )

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert first.json()["version"] == 1
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["version_id"] == first.json()["version_id"]
    assert changed.status_code == 201
    assert changed.json()["version"] == 2
    assert changed.json()["record_id"] == first.json()["record_id"]


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"acl": []}, 422, "acl_empty"),
        ({"acl": ["nonsense"]}, 422, "record_invalid"),
        ({"title": "   "}, 422, "record_invalid"),
        ({"occurred_at": "2026-11-01T08:00:00"}, 422, "record_invalid"),
        ({"content": "x" * 300_000}, 413, "record_too_large"),
    ],
)
def test_bad_records_are_rejected_with_a_stable_code(
    client: TestClient, overrides: dict[str, Any], status: int, code: str
) -> None:
    response = client.post("/ingest/records", json=record_body(**overrides))

    assert response.status_code == status
    assert response.json()["code"] == code


def test_a_record_with_a_missing_field_is_rejected(client: TestClient) -> None:
    body = record_body()
    del body["title"]

    response = client.post("/ingest/records", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "request_invalid"


def test_errors_use_the_problem_details_format(client: TestClient) -> None:
    response = client.get("/records/anything")

    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["status"] == 400
    assert problem["title"]
    assert problem["detail"]
    assert problem["code"] == "principal_required"


# -- reading versions ---------------------------------------------------------------


def test_a_reader_sees_every_version_with_the_latest_marked_current(client: TestClient) -> None:
    seed_people(client)
    first = ingest(client)
    second = ingest(client, content="Replace the seal every 400 hours.")
    headers = as_user("user:anna")

    current = client.get(f"/records/{first['record_id']}", headers=headers).json()
    versions = client.get(f"/records/{first['record_id']}/versions", headers=headers).json()
    old = client.get(f"/record-versions/{first['version_id']}", headers=headers).json()

    assert current["version_id"] == second["version_id"]
    assert current["is_current"] is True
    assert current["is_authoritative"] is True
    assert [v["version"] for v in versions] == [2, 1]
    assert [v["is_current"] for v in versions] == [True, False]
    assert versions[1]["content"] == "Replace the hydraulic seal every 500 hours."
    assert old["version"] == 1
    assert old["is_current"] is False


def test_an_unreadable_record_looks_exactly_like_a_missing_one(client: TestClient) -> None:
    seed_people(client)
    hidden = ingest(client)
    headers = as_user("user:bo")

    for hidden_path, missing_path in [
        (f"/records/{hidden['record_id']}", "/records/missing"),
        (f"/records/{hidden['record_id']}/versions", "/records/missing/versions"),
        (f"/record-versions/{hidden['version_id']}", "/record-versions/missing"),
    ]:
        hidden_response = client.get(hidden_path, headers=headers)
        missing_response = client.get(missing_path, headers=headers)
        assert hidden_response.status_code == missing_response.status_code == 404
        assert hidden_response.json() == missing_response.json()


def test_losing_access_in_a_new_version_hides_the_older_versions(client: TestClient) -> None:
    seed_people(client)
    first = ingest(client, acl=["group:maintenance"])
    ingest(client, acl=["group:sales"])

    old = client.get(f"/record-versions/{first['version_id']}", headers=as_user("user:anna"))
    current = client.get(f"/records/{first['record_id']}", headers=as_user("user:bo"))

    assert old.status_code == 404
    assert current.status_code == 200


# -- search -------------------------------------------------------------------------


def test_search_returns_readable_matches_with_a_passage(client: TestClient) -> None:
    seed_people(client)
    result = ingest(client)

    anna = client.get("/search", params={"q": "hydraulic"}, headers=as_user("user:anna")).json()
    bo = client.get("/search", params={"q": "hydraulic"}, headers=as_user("user:bo")).json()

    assert len(anna) == 1
    assert anna[0]["record_id"] == result["record_id"]
    assert anna[0]["version"] == 1
    assert "hydraulic" in anna[0]["passage"]
    assert anna[0]["is_authoritative"] is True
    assert bo == []


def test_search_filters_and_bad_queries(client: TestClient) -> None:
    seed_people(client)
    ingest(client)
    headers = as_user("user:anna")

    by_kind = client.get("/search", params={"q": "seal", "kind": "policy"}, headers=headers)
    by_source = client.get("/search", params={"q": "seal", "source": "wiki"}, headers=headers)
    blank = client.get("/search", params={"q": "  "}, headers=headers)

    assert by_kind.json() == []
    assert len(by_source.json()) == 1
    assert blank.status_code == 422
    assert blank.json()["code"] == "query_invalid"


# -- documentation ------------------------------------------------------------------


def test_the_api_docs_offer_a_way_to_set_the_principal_header(client: TestClient) -> None:
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]

    assert any(
        scheme.get("in") == "header" and scheme.get("name") == HEADER for scheme in schemes.values()
    )
