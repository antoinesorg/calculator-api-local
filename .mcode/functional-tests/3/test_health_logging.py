import os
import requests

BASE = f"http://localhost:{os.environ.get('PORT', '8000')}"


def test_health_ok():
    r = requests.get(BASE + "/health", timeout=10)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_existing_endpoint_after_logging_middleware():
    r = requests.post(BASE + "/add", json={"a": 2, "b": 3}, timeout=10)
    assert r.status_code == 200
    assert r.json() == {"result": 5}


def test_list_calculations():
    r = requests.get(BASE + "/calculations", timeout=10)
    assert r.status_code == 200
