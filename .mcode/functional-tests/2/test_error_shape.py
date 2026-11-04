import os
import pytest
import requests

BASE = f"http://localhost:{os.environ.get('PORT', '8000')}"
T = 10


def err(r, status, code):
    assert r.status_code == status
    e = r.json()["error"]
    assert set(e) == {"code", "message", "details"}
    assert e["code"] == code
    assert isinstance(e["message"], str)
    return e


@pytest.mark.parametrize("op,a,b,exp", [("add", 1, 2, 3), ("subtract", 5, 2, 3), ("multiply", 3, 4, 12), ("divide", 8, 2, 4)])
def test_happy_arithmetic(op, a, b, exp):
    r = requests.post(f"{BASE}/{op}", json={"a": a, "b": b}, timeout=T)
    assert r.status_code == 200 and r.json() == {"result": exp}


def test_happy_crud():
    r = requests.post(f"{BASE}/calculations", json={"operation": "div", "a": 9, "b": 3}, timeout=T)
    assert r.status_code == 201
    c = r.json()
    assert c["result"] == 3
    assert any(x["id"] == c["id"] for x in requests.get(f"{BASE}/calculations", timeout=T).json())
    assert requests.get(f"{BASE}/calculations/{c['id']}", timeout=T).status_code == 200
    assert requests.delete(f"{BASE}/calculations/{c['id']}", timeout=T).status_code == 204


def test_divide_by_zero_400():
    e = err(requests.post(f"{BASE}/divide", json={"a": 1, "b": 0}, timeout=T), 400, "bad_request")
    assert e["details"] is None


def test_calc_divide_by_zero_400():
    err(requests.post(f"{BASE}/calculations", json={"operation": "div", "a": 1, "b": 0}, timeout=T), 400, "bad_request")


def test_unknown_operation_400():
    err(requests.post(f"{BASE}/calculations", json={"operation": "pow", "a": 1, "b": 2}, timeout=T), 400, "bad_request")


def test_missing_field_422():
    e = err(requests.post(f"{BASE}/add", json={"a": 1}, timeout=T), 422, "validation_error")
    assert isinstance(e["details"], list) and e["details"]


@pytest.mark.parametrize("path", ["/add", "/subtract", "/multiply", "/divide"])
@pytest.mark.parametrize("val", ["NaN", "Infinity", "-Infinity"])
def test_nan_inf_422(path, val):
    r = requests.post(BASE + path, data=f'{{"a": {val}, "b": 1}}', headers={"Content-Type": "application/json"}, timeout=T)
    err(r, 422, "validation_error")


def test_nan_in_calculations_422():
    r = requests.post(f"{BASE}/calculations", data='{"operation":"add","a":NaN,"b":1}', headers={"Content-Type": "application/json"}, timeout=T)
    err(r, 422, "validation_error")


@pytest.mark.parametrize("cid", ["0", "-1"])
def test_id_not_positive_422(cid):
    err(requests.get(f"{BASE}/calculations/{cid}", timeout=T), 422, "validation_error")
    err(requests.delete(f"{BASE}/calculations/{cid}", timeout=T), 422, "validation_error")


def test_id_non_integer_422():
    err(requests.get(f"{BASE}/calculations/abc", timeout=T), 422, "validation_error")


def test_not_found_404():
    err(requests.get(f"{BASE}/calculations/999999999", timeout=T), 404, "not_found")
    err(requests.delete(f"{BASE}/calculations/999999999", timeout=T), 404, "not_found")


def test_unknown_route_404():
    err(requests.get(f"{BASE}/nope", timeout=T), 404, "not_found")


def test_method_not_allowed_405():
    err(requests.get(f"{BASE}/add", timeout=T), 405, "method_not_allowed")


def test_405_allow_header():
    r = requests.get(f"{BASE}/add", timeout=T)
    assert r.status_code == 405
    assert "POST" in r.headers.get("Allow", "")
