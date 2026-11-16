from typing import Any

from fastapi.testclient import TestClient

from tests.api_helpers import as_user, ingest_record, seed_people


def create_item(client: TestClient, user: str = "user:anna", **overrides: Any) -> Any:
    body: dict[str, Any] = {"kind": "question", "title": "Why is Press 3 slow?"}
    body.update(overrides)
    return client.post("/work-items", json=body, headers=as_user(user))


def shared_evidence(client: TestClient) -> str:
    """A public record, so everyone can read items that cite it."""
    return str(ingest_record(client, external_id="public", acl=["group:everyone"])["version_id"])


def test_work_item_routes_need_a_principal(api: TestClient) -> None:
    assert api.post("/work-items", json={"kind": "question", "title": "Q"}).status_code == 400
    assert api.get("/work-items").status_code == 400
    assert api.get("/work-items/x").status_code == 400


def test_creating_an_item(api: TestClient) -> None:
    seed_people(api)
    evidence = shared_evidence(api)

    response = create_item(
        api,
        description="Since Monday.",
        due_at="2026-11-20T09:00:00Z",
        evidence=[evidence],
    )

    assert response.status_code == 201
    item = response.json()
    assert item["kind"] == "question"
    assert item["status"] == "open"
    assert item["owner"] is None
    assert item["created_by"] == "user:anna"
    assert item["description"] == "Since Monday."
    assert item["due_at"].startswith("2026-11-20T09:00:00")
    assert item["evidence"] == [evidence]
    assert item["resolution"] is None


def test_invalid_items_are_rejected_with_stable_codes(api: TestClient) -> None:
    seed_people(api)

    bad_kind = create_item(api, kind="chore")
    no_zone = create_item(api, due_at="2026-11-20T09:00:00")
    missing_evidence = create_item(api, evidence=["missing"])
    ghost_owner = create_item(api, owner="user:ghost")
    no_title = api.post("/work-items", json={"kind": "question"}, headers=as_user("user:anna"))

    assert (bad_kind.status_code, bad_kind.json()["code"]) == (422, "work_item_invalid")
    assert (no_zone.status_code, no_zone.json()["code"]) == (422, "work_item_invalid")
    assert (missing_evidence.status_code, missing_evidence.json()["code"]) == (
        422,
        "node_not_found",
    )
    assert (ghost_owner.status_code, ghost_owner.json()["code"]) == (422, "owner_unknown")
    assert (no_title.status_code, no_title.json()["code"]) == (422, "request_invalid")


def test_listing_filters_and_paging(api: TestClient) -> None:
    seed_people(api)
    evidence = shared_evidence(api)
    ids = [create_item(api, title=f"Item {n}", evidence=[evidence]).json()["id"] for n in range(4)]
    action = create_item(api, kind="action", owner="user:bo", evidence=[evidence]).json()["id"]
    headers = as_user("user:bo")

    everything = api.get("/work-items", headers=headers).json()
    page_one = api.get("/work-items", params={"limit": 2}, headers=headers).json()
    page_two = api.get(
        "/work-items", params={"limit": 2, "before": page_one[-1]["id"]}, headers=headers
    ).json()
    actions = api.get("/work-items", params={"kind": "action"}, headers=headers).json()
    bos = api.get("/work-items", params={"owner": "user:bo"}, headers=headers).json()
    open_items = api.get("/work-items", params={"status": "open"}, headers=headers).json()

    assert [i["id"] for i in everything] == [action, *reversed(ids)]
    assert [i["id"] for i in page_one] == [action, ids[3]]
    assert [i["id"] for i in page_two] == [ids[2], ids[1]]
    assert [i["id"] for i in actions] == [action]
    assert [i["id"] for i in bos] == [action]
    assert len(open_items) == 4


def test_an_unreadable_item_looks_exactly_like_a_missing_one(api: TestClient) -> None:
    seed_people(api)
    private = create_item(api).json()["id"]  # no evidence: only Anna can read it

    for path, method in [
        (f"/work-items/{private}", "get"),
        (f"/work-items/{private}/history", "get"),
        (f"/work-items/{private}/claim", "post"),
    ]:
        missing_path = path.replace(private, "missing")
        hidden = getattr(api, method)(path, headers=as_user("user:cy"))
        missing = getattr(api, method)(missing_path, headers=as_user("user:cy"))
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json() == missing.json()


def test_claiming_and_the_loser_being_told_who_owns_it(api: TestClient) -> None:
    seed_people(api)
    item = create_item(api, evidence=[shared_evidence(api)]).json()["id"]

    won = api.post(f"/work-items/{item}/claim", headers=as_user("user:bo"))
    lost = api.post(f"/work-items/{item}/claim", headers=as_user("user:cy"))

    assert won.status_code == 200
    assert won.json()["owner"] == "user:bo"
    assert won.json()["status"] == "investigating"
    assert lost.status_code == 409
    assert lost.json()["code"] == "already_owned"
    assert lost.json()["owner"] == "user:bo"


def test_assigning(api: TestClient) -> None:
    seed_people(api)
    item = create_item(api, evidence=[shared_evidence(api)]).json()["id"]
    headers = as_user("user:anna")

    assigned = api.post(f"/work-items/{item}/assign", json={"owner": "user:cy"}, headers=headers)
    ghost = api.post(f"/work-items/{item}/assign", json={"owner": "user:ghost"}, headers=headers)
    group = api.post(
        f"/work-items/{item}/assign", json={"owner": "group:maintenance"}, headers=headers
    )

    assert assigned.status_code == 200
    assert (assigned.json()["owner"], assigned.json()["status"]) == ("user:cy", "assigned")
    assert ghost.json()["code"] == "owner_unknown"
    assert group.json()["code"] == "owner_must_be_user"


def test_transitions_and_their_rules(api: TestClient) -> None:
    seed_people(api)
    item = create_item(api, evidence=[shared_evidence(api)]).json()["id"]
    headers = as_user("user:anna")

    no_text = api.post(f"/work-items/{item}/transition", json={"to": "resolved"}, headers=headers)
    bad_edge = api.post(f"/work-items/{item}/transition", json={"to": "blocked"}, headers=headers)
    resolved = api.post(
        f"/work-items/{item}/transition",
        json={"to": "resolved", "resolution": "Seal replaced."},
        headers=headers,
    )
    reopened = api.post(f"/work-items/{item}/transition", json={"to": "reopened"}, headers=headers)

    assert (no_text.status_code, no_text.json()["code"]) == (422, "resolution_required")
    assert (bad_edge.status_code, bad_edge.json()["code"]) == (409, "invalid_transition")
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution"] == "Seal replaced."
    assert reopened.json()["status"] == "reopened"
    assert reopened.json()["resolution"] is None


def test_the_history_shows_every_step_in_order(api: TestClient) -> None:
    seed_people(api)
    item = create_item(api, evidence=[shared_evidence(api)]).json()["id"]
    anna, bo = as_user("user:anna"), as_user("user:bo")
    api.post(f"/work-items/{item}/claim", headers=bo)
    api.post(f"/work-items/{item}/assign", json={"owner": "user:cy"}, headers=anna)
    api.post(
        f"/work-items/{item}/transition",
        json={"to": "resolved", "resolution": "Done."},
        headers=anna,
    )

    history = api.get(f"/work-items/{item}/history", headers=anna).json()
    via_events = api.get(
        "/events", params={"subject_type": "work_item", "subject_id": item}, headers=anna
    ).json()

    assert [e["type"] for e in history] == [
        "work_item.created",
        "work_item.claimed",
        "work_item.assigned",
        "work_item.status_changed",
    ]
    assert [e["actor"] for e in history] == ["user:anna", "user:bo", "user:anna", "user:anna"]
    assert history[1]["payload"]["before"] == {"owner": None, "status": "open"}
    assert [e["seq"] for e in history] == sorted(e["seq"] for e in history)
    assert via_events == history


def test_events_paging(api: TestClient) -> None:
    seed_people(api)
    item = create_item(api, evidence=[shared_evidence(api)]).json()["id"]
    api.post(f"/work-items/{item}/claim", headers=as_user("user:bo"))
    params = {"subject_type": "work_item", "subject_id": item}

    first = api.get("/events", params={**params, "limit": 1}, headers=as_user("user:anna")).json()
    rest = api.get(
        "/events", params={**params, "after_seq": first[0]["seq"]}, headers=as_user("user:anna")
    ).json()

    assert [e["type"] for e in first] == ["work_item.created"]
    assert [e["type"] for e in rest] == ["work_item.claimed"]
