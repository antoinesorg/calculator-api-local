"""End-to-end tests for every route in server.py."""

import pytest


def create_calculation(client, operation="add", a=1, b=2):
    response = client.post("/calculations", json={"operation": operation, "a": a, "b": b})
    assert response.status_code == 201
    return response.json()


def assert_default_422(response):
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}
    return body


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
    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot divide by zero"}


@pytest.mark.parametrize("path", ["/add", "/subtract", "/multiply", "/divide"])
def test_invalid_body_returns_default_422(client, path):
    response = client.post(path, json={"a": "x"})
    body = assert_default_422(response)
    assert isinstance(body["detail"], list)
    missing_or_invalid = {tuple(err["loc"]) for err in body["detail"]}
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
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unknown operation: pow. Use: ['add', 'sub', 'mul', 'div']"
    }


def test_create_calculation_divide_by_zero(client):
    response = client.post("/calculations", json={"operation": "div", "a": 1, "b": 0})
    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot divide by zero"}


def test_create_calculation_invalid_body(client):
    response = client.post("/calculations", json={"operation": "add"})
    assert_default_422(response)


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
    assert_default_422(response)


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
    assert response.status_code == 404
    assert response.json() == {"detail": "Calculation not found"}


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
