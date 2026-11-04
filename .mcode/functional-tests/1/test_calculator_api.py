import os
import pytest
import requests

BASE = f"http://localhost:{os.environ.get('PORT', '8000')}"
T = 10


def post(path, body):
    return requests.post(BASE + path, json=body, timeout=T)


@pytest.mark.parametrize("op,a,b,exp", [("add", 2, 3, 5), ("subtract", 5, 3, 2), ("multiply", 4, 2.5, 10), ("divide", 9, 3, 3)])
def test_arithmetic_happy(op, a, b, exp):
    r = post("/" + op, {"a": a, "b": b})
    assert r.status_code == 200
    assert r.json() == {"result": exp}


def test_divide_by_zero():
    r = post("/divide", {"a": 1, "b": 0})
    assert r.status_code == 400
    assert r.json()["error"] == {"code": "bad_request", "message": "Cannot divide by zero", "details": None}


def test_missing_field_422():
    r = post("/add", {"a": 1})
    assert r.status_code == 422
    assert isinstance(r.json()["error"]["details"], list)


def test_invalid_type_422():
    r = post("/multiply", {"a": "x", "b": 1})
    assert r.status_code == 422
    assert isinstance(r.json()["error"]["details"], list)


def test_crud_lifecycle():
    r1 = post("/calculations", {"operation": "add", "a": 1, "b": 2})
    assert r1.status_code == 201
    c1 = r1.json()
    assert c1["result"] == 3 and c1["operation"] == "add" and "created_at" in c1
    r2 = post("/calculations", {"operation": "mul", "a": 3, "b": 4})
    c2 = r2.json()
    assert r2.status_code == 201 and c2["result"] == 12
    try:
        lst = requests.get(BASE + "/calculations", timeout=T)
        assert lst.status_code == 200
        ids = [c["id"] for c in lst.json()]
        assert ids.index(c2["id"]) < ids.index(c1["id"])
        g = requests.get(f"{BASE}/calculations/{c1['id']}", timeout=T)
        assert g.status_code == 200 and g.json()["id"] == c1["id"]
    finally:
        for c in (c1, c2):
            d = requests.delete(f"{BASE}/calculations/{c['id']}", timeout=T)
            assert d.status_code == 204
    assert requests.get(f"{BASE}/calculations/{c1['id']}", timeout=T).status_code == 404


def test_create_unknown_operation():
    r = post("/calculations", {"operation": "pow", "a": 1, "b": 2})
    assert r.status_code == 400


def test_create_div_zero():
    assert post("/calculations", {"operation": "div", "a": 1, "b": 0}).status_code == 400


def test_get_missing():
    r = requests.get(BASE + "/calculations/99999999", timeout=T)
    assert r.status_code == 404


def test_delete_missing():
    assert requests.delete(BASE + "/calculations/99999999", timeout=T).status_code == 404


def test_create_missing_field():
    assert post("/calculations", {"operation": "add"}).status_code == 422
