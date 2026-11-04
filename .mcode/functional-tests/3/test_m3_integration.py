import glob
import json
import os
import time

import pytest
import requests

BASE = f"http://localhost:{os.environ.get('PORT', '8000')}"
T = 10


def _log_files():
    d = os.path.join(os.environ.get("MCODE_DIR", "/l2l/mcode"), "lifecycle/target/runs")
    return sorted(glob.glob(d + "/*_run_std*.log"), key=os.path.getmtime)


def _access_lines(request_id):
    time.sleep(0.3)
    out = []
    for f in _log_files():
        for line in open(f, errors="replace"):
            if request_id in line and line.startswith("{"):
                out.append(json.loads(line))
    return out


def assert_error(r, status, code):
    assert r.status_code == status
    body = r.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)


@pytest.mark.parametrize("path,a,b,exp", [
    ("/add", 2, 3, 5), ("/subtract", 5, 3, 2), ("/multiply", 4, 3, 12), ("/divide", 10, 4, 2.5)])
def test_arithmetic(path, a, b, exp):
    r = requests.post(BASE + path, json={"a": a, "b": b}, timeout=T)
    assert r.status_code == 200
    assert r.json() == {"result": exp}
    assert r.headers.get("x-request-id")


def test_divide_by_zero_400():
    r = requests.post(BASE + "/divide", json={"a": 1, "b": 0}, timeout=T)
    assert_error(r, 400, "bad_request")


@pytest.mark.parametrize("body", [{"a": 1}, {"a": "x", "b": 1}, {}])
def test_validation_422(body):
    r = requests.post(BASE + "/add", json=body, timeout=T)
    assert_error(r, 422, "validation_error")
    assert isinstance(r.json()["error"]["details"], list)


def test_nan_inf_422():
    for raw in ('{"a": NaN, "b": 1}', '{"a": Infinity, "b": 1}'):
        r = requests.post(BASE + "/add", data=raw, headers={"Content-Type": "application/json"}, timeout=T)
        assert_error(r, 422, "validation_error")


def test_crud_flow():
    r = requests.post(BASE + "/calculations", json={"operation": "add", "a": 1, "b": 2}, timeout=T)
    assert r.status_code == 201
    cid = r.json()["id"]
    assert r.json()["result"] == 3
    assert requests.get(f"{BASE}/calculations/{cid}", timeout=T).status_code == 200
    assert any(c["id"] == cid for c in requests.get(BASE + "/calculations", timeout=T).json())
    assert requests.delete(f"{BASE}/calculations/{cid}", timeout=T).status_code == 204
    assert_error(requests.get(f"{BASE}/calculations/{cid}", timeout=T), 404, "not_found")
    assert_error(requests.delete(f"{BASE}/calculations/{cid}", timeout=T), 404, "not_found")


def test_create_unknown_operation_400():
    r = requests.post(BASE + "/calculations", json={"operation": "pow", "a": 1, "b": 2}, timeout=T)
    assert_error(r, 400, "bad_request")


def test_create_divide_zero_400():
    r = requests.post(BASE + "/calculations", json={"operation": "div", "a": 1, "b": 0}, timeout=T)
    assert_error(r, 400, "bad_request")


@pytest.mark.parametrize("cid", ["0", "-1", "abc"])
def test_bad_id_422(cid):
    assert_error(requests.get(f"{BASE}/calculations/{cid}", timeout=T), 422, "validation_error")
    assert_error(requests.delete(f"{BASE}/calculations/{cid}", timeout=T), 422, "validation_error")


def test_unknown_route_404():
    assert_error(requests.get(BASE + "/nope", timeout=T), 404, "not_found")


def test_method_not_allowed_405():
    r = requests.get(BASE + "/add", timeout=T)
    assert_error(r, 405, "method_not_allowed")
    r = requests.post(BASE + "/health", timeout=T)
    assert_error(r, 405, "method_not_allowed")


def test_health_body():
    r = requests.get(BASE + "/health", timeout=T)
    assert r.status_code == 200 and r.json() == {"status": "ok"}


@pytest.mark.parametrize("method,path,kw,status", [
    ("GET", "/health", {}, 200),
    ("GET", "/nope", {}, 404),
    ("GET", "/add", {}, 405),
    ("POST", "/add", {"json": {"a": "x"}}, 422),
    ("GET", "/calculations/0", {}, 422),
    ("POST", "/divide", {"json": {"a": 1, "b": 0}}, 400),
])
def test_logging_coexists_with_error_handlers(method, path, kw, status):
    rid = f"ftrun-{method}-{path.strip('/')}-{status}-{time.time_ns()}"
    r = requests.request(method, BASE + path, headers={"X-Request-Id": rid}, timeout=T, **kw)
    assert r.status_code == status
    assert r.headers.get("x-request-id") == rid
    if status != 200:
        assert "error" in r.json()
    lines = _access_lines(rid)
    assert len(lines) == 1, lines
    e = lines[0]
    assert e["method"] == method and e["path"] == path and e["status"] == status
    assert e["request_id"] == rid and e["duration_ms"] >= 0


def test_generated_request_id_and_no_body_logged():
    r = requests.post(BASE + "/add", json={"a": 123456.789, "b": 1}, timeout=T)
    rid = r.headers["x-request-id"]
    assert len(rid) >= 32
    lines = _access_lines(rid)
    assert len(lines) == 1
    assert "123456.789" not in json.dumps(lines[0])
