"""End-to-end tests for every route in server.py."""

import pytest


def create_calculation(client, operation="add", a=1, b=2):
    response = client.post("/calculations", json={"operation": operation, "a": a, "b": b})
    assert response.status_code == 201
    return response.json()


def assert_error(response, status, code):
    """Assert the uniform error shape and return the error object."""
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body["error"]


def assert_validation_error(response):
    return assert_error(response, 422, "validation_error")


@pytest.mark.parametrize(
    ("path", "a", "b", "expected"),
    [
        ("/add", 5, 3, 8.0),
        ("/subtract", 5, 3, 2.0),
        ("/multiply", 7, 6, 42.0),
        ("/divide", 10, 4, 2.5),
        ("/add", 0.5, 0.25, 0.75),
    ],
)
def test_calculator_endpoints(client, path, a, b, expected):
    response = client.post(path, json={"a": a, "b": b})
    assert response.status_code == 200
    assert response.json() == {"result": expected}


def test_divide_by_zero_returns_400(client):
    response = client.post("/divide", json={"a": 1, "b": 0})
    error = assert_error(response, 400, "bad_request")
    assert error["message"] == "Cannot divide by zero"
    assert error["details"] is None


@pytest.mark.parametrize("path", ["/add", "/subtract", "/multiply", "/divide"])
def test_invalid_body_returns_uniform_422(client, path):
    response = client.post(path, json={"a": "x"})
    error = assert_validation_error(response)
    assert isinstance(error["details"], list)
    missing_or_invalid = {tuple(err["loc"]) for err in error["details"]}
    assert ("body", "a") in missing_or_invalid
    assert ("body", "b") in missing_or_invalid


def test_create_calculation(client):
    response = client.post("/calculations", json={"operation": "mul", "a": 7, "b": 6})
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert body["operation"] == "mul"
    assert body["a"] == 7.0
    assert body["b"] == 6.0
    assert body["result"] == 42.0
    assert "created_at" in body


@pytest.mark.parametrize(
    ("operation", "a", "b", "expected"),
    [("add", 1, 2, 3.0), ("sub", 5, 2, 3.0), ("mul", 2, 4, 8.0), ("div", 9, 3, 3.0)],
)
def test_create_calculation_all_operations(client, operation, a, b, expected):
    response = client.post("/calculations", json={"operation": operation, "a": a, "b": b})
    assert response.status_code == 201
    assert response.json()["result"] == expected


def test_create_calculation_unknown_operation(client):
    response = client.post("/calculations", json={"operation": "pow", "a": 1, "b": 2})
    # Design decision: the unknown-operation check stays at route level, so it
    # keeps its M1 status of 400 (not 422) and only the body shape changes.
    error = assert_error(response, 400, "bad_request")
    assert error["message"] == "Unknown operation: pow. Use: ['add', 'sub', 'mul', 'div']"


def test_create_calculation_divide_by_zero(client):
    response = client.post("/calculations", json={"operation": "div", "a": 1, "b": 0})
    error = assert_error(response, 400, "bad_request")
    assert error["message"] == "Cannot divide by zero"


def test_create_calculation_invalid_body(client):
    response = client.post("/calculations", json={"operation": "add"})
    error = assert_validation_error(response)
    assert [tuple(e["loc"]) for e in error["details"]] == [("body", "a"), ("body", "b")]


def test_list_calculations_empty(client):
    response = client.get("/calculations")
    assert response.status_code == 200
    assert response.json() == []


def test_list_calculations_newest_first(client):
    for a in (1, 2, 3):
        create_calculation(client, "add", a, 0)
    response = client.get("/calculations")
    assert response.status_code == 200
    assert [c["a"] for c in response.json()] == [3.0, 2.0, 1.0]


def test_get_calculation(client):
    created = create_calculation(client)
    response = client.get(f"/calculations/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_calculation_non_integer_id(client):
    response = client.get("/calculations/abc")
    assert_validation_error(response)


def test_delete_calculation(client):
    created = create_calculation(client)
    response = client.delete(f"/calculations/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/calculations/{created['id']}").status_code == 404
    assert client.get("/calculations").json() == []


@pytest.mark.parametrize("method", ["get", "delete"])
def test_missing_calculation_returns_404(client, method):
    response = getattr(client, method)("/calculations/999")
    error = assert_error(response, 404, "not_found")
    assert error["message"] == "Calculation not found"
    assert error["details"] is None


# --- Negative validation tests ---


@pytest.mark.parametrize("path", ["/add", "/subtract", "/multiply", "/divide"])
@pytest.mark.parametrize("body", [{}, {"a": 1}, {"b": 1}])
def test_missing_fields_return_422(client, path, body):
    assert_validation_error(client.post(path, json=body))


@pytest.mark.parametrize("path", ["/add", "/subtract", "/multiply", "/divide"])
@pytest.mark.parametrize("value", ["x", None, [1], {"v": 1}, True])
def test_wrong_types_return_422_or_coerce(client, path, value):
    response = client.post(path, json={"a": value, "b": 1})
    if value is True:  # pydantic lax mode coerces bool to float, as in M1
        assert response.status_code == 200
    else:
        assert_validation_error(response)


@pytest.mark.parametrize("path", ["/add", "/subtract", "/multiply", "/divide"])
@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("field", ["a", "b"])
def test_non_finite_numbers_rejected(client, path, literal, field):
    payload = {"a": "1", "b": "1"}
    payload[field] = literal
    raw = '{"a": %s, "b": %s}' % (payload["a"], payload["b"])
    response = client.post(path, content=raw, headers={"content-type": "application/json"})
    error = assert_validation_error(response)
    assert ("body", field) in {tuple(e["loc"]) for e in error["details"]}


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_rejected_on_create(client, literal):
    raw = '{"operation": "add", "a": %s, "b": 1}' % literal
    response = client.post(
        "/calculations", content=raw, headers={"content-type": "application/json"}
    )
    assert_validation_error(response)
    assert client.get("/calculations").json() == []


@pytest.mark.parametrize("literal", ["inf", "nan", "-inf"])
def test_non_finite_strings_rejected(client, literal):
    assert_validation_error(client.post("/add", json={"a": literal, "b": 1}))


@pytest.mark.parametrize("operation", ["pow", "ADD", "", "addition"])
def test_unknown_operation_returns_400(client, operation):
    response = client.post("/calculations", json={"operation": operation, "a": 1, "b": 2})
    assert_error(response, 400, "bad_request")


def test_non_string_operation_returns_422(client):
    response = client.post("/calculations", json={"operation": 5, "a": 1, "b": 2})
    assert_validation_error(response)


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", "1.5"])
@pytest.mark.parametrize("method", ["get", "delete"])
def test_bad_calculation_id_returns_422(client, method, bad_id):
    assert_validation_error(getattr(client, method)(f"/calculations/{bad_id}"))


def test_unknown_route_returns_uniform_404(client):
    assert_error(client.get("/nope"), 404, "not_found")


def test_wrong_method_returns_uniform_405(client):
    assert_error(client.get("/add"), 405, "method_not_allowed")


def test_success_payloads_unchanged(client):
    assert client.post("/add", json={"a": 1.5, "b": 2}).json() == {"result": 3.5}
    created = create_calculation(client, "div", 9, 3)
    assert set(created) == {"id", "operation", "a", "b", "result", "created_at"}
    assert client.get("/calculations").json() == [created]


def test_isolation_between_tests(client):
    assert client.get("/calculations").json() == []


def test_main_runs_uvicorn_with_port(monkeypatch):
    import server

    calls = {}
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setattr(server.uvicorn, "run", lambda app, **kw: calls.update(kw, app=app))
    server.main()
    assert calls["port"] == 9123
    assert calls["host"] == "0.0.0.0"
    assert calls["app"] is server.app


def test_lifespan_creates_tables_on_engine(monkeypatch, engine):
    import asyncio

    import server

    monkeypatch.setattr(server, "engine", engine)
    called = []
    monkeypatch.setattr(server.SQLModel.metadata, "create_all", lambda e: called.append(e))

    async def run():
        async with server.lifespan(server.app):
            pass

    asyncio.run(run())
    assert called == [engine]
