"""Shared fixtures: isolated in-memory database and TestClient."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import server


@pytest.fixture
def engine() -> Iterator:
    """Function-scoped in-memory SQLite engine with tables created."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    """A session bound to the in-memory engine."""
    with Session(engine) as db_session:
        yield db_session


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    """TestClient with get_session overridden. Used without a context manager so the
    app lifespan (which would create calculator.db) never runs."""

    def override_get_session() -> Iterator[Session]:
        with Session(engine) as db_session:
            yield db_session

    server.app.dependency_overrides[server.get_session] = override_get_session
    test_client = TestClient(server.app)
    yield test_client
    server.app.dependency_overrides.clear()


@pytest.fixture(autouse=True, scope="session")
def _no_database_file() -> Iterator[None]:
    """Fail the run if any test wrote calculator.db."""
    db_file = Path("calculator.db")
    existed = db_file.exists()
    yield
    assert existed or not db_file.exists(), "tests must not create calculator.db"
