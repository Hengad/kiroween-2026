from fastapi.testclient import TestClient

EXPECTED_OPERATIONS = {
    ("get", "/health"),
    ("put", "/principals/{principal_id}"),
    ("get", "/principals"),
    ("put", "/users/{user_id}/memberships"),
    ("post", "/ingest/records"),
    ("post", "/ingest/entities"),
    ("post", "/ingest/relations"),
    ("get", "/records/{record_id}"),
    ("get", "/records/{record_id}/versions"),
    ("get", "/record-versions/{version_id}"),
    ("get", "/search"),
    ("get", "/entities/{entity_id}"),
    ("get", "/nodes/{node_type}/{node_id}/relations"),
    ("post", "/work-items"),
    ("get", "/work-items"),
    ("get", "/work-items/{item_id}"),
    ("post", "/work-items/{item_id}/claim"),
    ("post", "/work-items/{item_id}/assign"),
    ("post", "/work-items/{item_id}/transition"),
    ("get", "/work-items/{item_id}/history"),
    ("get", "/events"),
}


def test_the_api_description_lists_every_planned_operation(api: TestClient) -> None:
    paths = api.get("/openapi.json").json()["paths"]
    operations = {(method, path) for path, item in paths.items() for method in item}

    assert operations == EXPECTED_OPERATIONS


def test_the_error_format_is_part_of_the_api_description(api: TestClient) -> None:
    spec = api.get("/openapi.json").json()

    problem = spec["components"]["schemas"]["ProblemDetails"]
    assert {"status", "detail", "code"} <= set(problem["properties"])
    for path, item in spec["paths"].items():
        if path == "/health":
            continue
        for method, operation in item.items():
            assert "default" in operation["responses"], f"{method} {path} has no error response"


def test_reading_endpoints_require_the_principal_scheme(api: TestClient) -> None:
    spec = api.get("/openapi.json").json()

    secured = spec["paths"]["/work-items"]["get"]["security"]
    open_ = spec["paths"]["/ingest/records"]["post"].get("security")

    assert secured
    assert open_ is None
