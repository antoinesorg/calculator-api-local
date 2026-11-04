"""Tests for request logging middleware and /health."""

import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

import server

SENTINEL = "SECRET-SENTINEL-12345"


def access_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == server.REQUEST_LOGGER_NAME]


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_log_has_required_fields(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=server.REQUEST_LOGGER_NAME):
        client.post("/add", json={"a": 1, "b": 2})
    (record,) = access_records(caplog)
    assert record.method == "POST"  # type: ignore[attr-defined]
    assert record.path == "/add"  # type: ignore[attr-defined]
    assert record.status == 200  # type: ignore[attr-defined]
    assert record.duration_ms >= 0  # type: ignore[attr-defined]
    uuid.UUID(record.request_id)  # type: ignore[attr-defined]


def test_formatter_emits_json(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=server.REQUEST_LOGGER_NAME):
        client.get("/health")
    line = json.loads(server.JsonFormatter().format(access_records(caplog)[0]))
    assert set(server.LOG_FIELDS) <= set(line)
    assert line["status"] == 200


def test_error_status_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=server.REQUEST_LOGGER_NAME):
        client.post("/divide", json={"a": 1, "b": 0})
        client.get("/calculations/999")
    assert [r.status for r in access_records(caplog)] == [400, 404]  # type: ignore[attr-defined]


def test_request_id_header_generated_and_honored(client: TestClient) -> None:
    assert uuid.UUID(client.get("/health").headers["X-Request-ID"])
    response = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"


def test_bodies_not_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        client.post("/calculations", json={"operation": SENTINEL, "a": 1, "b": 2})
        client.post("/add", json={"a": SENTINEL, "b": 2})
    assert access_records(caplog)
    formatter = server.JsonFormatter()
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()
        assert SENTINEL not in formatter.format(record)
        assert SENTINEL not in str(record.__dict__)
    assert SENTINEL not in caplog.text


def test_unhandled_exception_logged_as_500(caplog: pytest.LogCaptureFixture) -> None:
    @server.app.get("/_boom")
    def boom() -> None:
        raise RuntimeError("boom")

    try:
        crashing = TestClient(server.app, raise_server_exceptions=False)
        with caplog.at_level(logging.INFO, logger=server.REQUEST_LOGGER_NAME):
            response = crashing.get("/_boom")
        assert response.status_code == 500
        assert access_records(caplog)[-1].status == 500  # type: ignore[attr-defined]
    finally:
        server.app.router.routes.pop()


def test_existing_endpoints_unaffected(client: TestClient) -> None:
    assert client.post("/multiply", json={"a": 3, "b": 4}).json() == {"result": 12.0}
    created = client.post("/calculations", json={"operation": "add", "a": 1, "b": 2})
    assert created.status_code == 201
    assert client.get("/calculations").status_code == 200


@pytest.fixture
def restore_request_logger():
    logger = logging.getLogger(server.REQUEST_LOGGER_NAME)
    level, handlers = logger.level, logger.handlers[:]
    yield logger
    logger.setLevel(level)
    logger.handlers[:] = handlers


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("DEBUG", logging.DEBUG),
        ("warning", logging.WARNING),
        ("verbose", logging.INFO),
        (None, logging.INFO),
    ],
)
def test_setup_logging_level(
    monkeypatch: pytest.MonkeyPatch,
    restore_request_logger: logging.Logger,
    value: str | None,
    expected: int,
) -> None:
    if value is None:
        monkeypatch.delenv("LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("LOG_LEVEL", value)
    server.setup_logging()
    assert restore_request_logger.level == expected


def test_setup_logging_attaches_handler_once(restore_request_logger: logging.Logger) -> None:
    server.setup_logging()
    server.setup_logging()
    assert sum(getattr(h, "_calculator_json", False) for h in restore_request_logger.handlers) == 1
