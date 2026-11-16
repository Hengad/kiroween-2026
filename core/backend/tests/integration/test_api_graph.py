from typing import Any

from fastapi.testclient import TestClient

from tests.api_helpers import as_user, ingest_record, seed_people


def machine(client: TestClient, key: str = "press-3", name: str = "Press 3", **extra: Any) -> Any:
    return client.post(
        "/ingest/entities",
        json={"entity_type": "machine", "key": key, "name": name, "attributes": extra},
    )


def link(client: TestClient, version_id: str, entity_id: str, relation_type: str = "about") -> Any:
    return client.post(
        "/ingest/relations",
        json={
            "relation_type": relation_type,
            "from": {"kind": "record_version", "id": version_id},
            "to": {"kind": "entity", "id": entity_id},
        },
    )


def test_entities_are_created_then_updated_in_place(api: TestClient) -> None:
    created = machine(api, line=1)
    same = machine(api, line=1)
    renamed = machine(api, name="Press Three", line=1)

    assert created.status_code == 201
    assert created.json()["created"] is True
    assert created.json()["entity_type"] == "machine"
    assert created.json()["attributes"] == {"line": 1}
    assert same.status_code == 200
    assert same.json()["id"] == created.json()["id"]
    assert same.json()["created"] is False
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Press Three"
    assert renamed.json()["id"] == created.json()["id"]


def test_an_unregistered_entity_type_is_rejected(api: TestClient) -> None:
    response = api.post(
        "/ingest/entities",
        json={"entity_type": "spaceship", "key": "x", "name": "X", "attributes": {}},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unknown_entity_type"


def test_relations_are_created_once_and_use_from_and_to(api: TestClient) -> None:
    seed_people(api)
    version = ingest_record(api)["version_id"]
    entity = machine(api).json()["id"]

    first = link(api, version, entity)
    again = link(api, version, entity)

    assert first.status_code == 201
    assert first.json()["from"] == {"kind": "record_version", "id": version}
    assert first.json()["to"] == {"kind": "entity", "id": entity}
    assert first.json()["relation_type"] == "about"
    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]


def test_relations_to_missing_nodes_or_with_unknown_types_are_rejected(api: TestClient) -> None:
    version = ingest_record(api)["version_id"]
    entity = machine(api).json()["id"]

    missing = link(api, version, "missing")
    unknown_type = link(api, version, entity, relation_type="teleports_to")

    assert missing.status_code == 422
    assert missing.json()["code"] == "node_not_found"
    assert unknown_type.status_code == 422
    assert unknown_type.json()["code"] == "unknown_relation_type"


def test_an_entity_lists_only_the_linked_records_the_reader_may_read(api: TestClient) -> None:
    seed_people(api)
    private = ingest_record(api, external_id="private", acl=["group:maintenance"])
    public = ingest_record(api, external_id="public", acl=["group:everyone"])
    entity = machine(api).json()["id"]
    link(api, private["version_id"], entity)
    link(api, public["version_id"], entity)

    for_anna = api.get(f"/entities/{entity}", headers=as_user("user:anna")).json()
    for_bo = api.get(f"/entities/{entity}", headers=as_user("user:bo")).json()

    assert for_anna["entity"]["name"] == "Press 3"
    assert {r["version_id"] for r in for_anna["records"]} == {
        private["version_id"],
        public["version_id"],
    }
    assert [r["version_id"] for r in for_bo["records"]] == [public["version_id"]]


def test_reading_a_missing_entity_is_not_found(api: TestClient) -> None:
    seed_people(api)

    response = api.get("/entities/missing", headers=as_user("user:anna"))

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_node_relations_are_filtered_by_what_the_reader_may_read(api: TestClient) -> None:
    seed_people(api)
    private = ingest_record(api, external_id="private", acl=["group:maintenance"])
    entity = machine(api).json()["id"]
    link(api, private["version_id"], entity)

    for_anna = api.get(f"/nodes/entity/{entity}/relations", headers=as_user("user:anna"))
    for_bo = api.get(f"/nodes/entity/{entity}/relations", headers=as_user("user:bo"))
    by_version = api.get(
        f"/nodes/record_version/{private['version_id']}/relations", headers=as_user("user:anna")
    )

    assert len(for_anna.json()) == 1
    assert for_bo.json() == []
    assert len(by_version.json()) == 1


def test_an_unknown_node_type_is_rejected(api: TestClient) -> None:
    seed_people(api)

    response = api.get("/nodes/planet/x/relations", headers=as_user("user:anna"))

    assert response.status_code == 422
    assert response.json()["code"] == "request_invalid"


def test_search_can_be_limited_to_records_linked_to_an_entity(api: TestClient) -> None:
    seed_people(api)
    linked = ingest_record(api, external_id="a", title="Seal A")
    ingest_record(api, external_id="b", title="Seal B")
    entity = machine(api).json()["id"]
    link(api, linked["version_id"], entity)

    hits = api.get(
        "/search", params={"q": "seal", "entity": entity}, headers=as_user("user:anna")
    ).json()

    assert [h["title"] for h in hits] == ["Seal A"]


def test_events_can_be_read_for_a_record_an_entity_and_a_relation(api: TestClient) -> None:
    seed_people(api)
    record = ingest_record(api)
    entity = machine(api).json()["id"]
    relation = link(api, record["version_id"], entity).json()["id"]

    def types(subject_type: str, subject_id: str, user: str = "user:anna") -> list[str]:
        response = api.get(
            "/events",
            params={"subject_type": subject_type, "subject_id": subject_id},
            headers=as_user(user),
        )
        assert response.status_code == 200
        return [event["type"] for event in response.json()]

    assert types("record", record["record_id"]) == ["record.version_added"]
    assert types("entity", entity) == ["entity.created"]
    assert types("relation", relation) == ["relation.created"]
    # Bo cannot read the record or the relation, so those histories look empty to him.
    assert types("record", record["record_id"], "user:bo") == []
    assert types("relation", relation, "user:bo") == []
    assert types("entity", entity, "user:bo") == ["entity.created"]
