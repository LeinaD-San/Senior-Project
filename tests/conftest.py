"""
Shared test fixtures.

Strategy:
- Force DATABASE_URL to an in-memory SQLite before importing the app modules,
  so that nothing in main.py / database.py opens a real Postgres connection.
- Replace the engine/SessionLocal in both `database` and `main` with a SQLite
  StaticPool engine so the same in-memory DB is shared across requests.
- Override FastAPI's `get_db` dependency to use the test SessionLocal.
- Re-create tables from `models.Base.metadata` before each test for isolation.
- Stub the GOOGLE_MAPS_API_KEY so endpoints that gate on it don't 500 with
  the "key not set" branch unless the test explicitly wants that.
"""
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `import main` works when pytest
# runs from any CWD.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# These have to be set BEFORE importing database/main.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-google-maps-key")
os.environ.setdefault("GOOGLE_MAPS_JS_API_KEY", "test-google-maps-js-key")
# Don't accidentally hit OpenAI in tests.
os.environ.pop("OPENAI_API_KEY", None)

from datetime import timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import database  # noqa: E402

# Build a single in-memory SQLite engine shared across the whole test run.
# StaticPool keeps one connection alive so the schema persists between
# session checkouts.
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)

# Patch the engine/SessionLocal that the app modules reference.
database.engine = TEST_ENGINE
database.SessionLocal = TestingSessionLocal

import models  # noqa: E402
import main  # noqa: E402

# main.py imported `engine` and `SessionLocal` by name, so swap those too.
main.engine = TEST_ENGINE
main.SessionLocal = TestingSessionLocal


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


main.app.dependency_overrides[main.get_db] = _override_get_db


# SQLite drops tzinfo from DateTime(timezone=True) columns. Postgres (the real
# DB) keeps it. Re-attach UTC on load so comparisons like
# `session.expires_at <= datetime.now(timezone.utc)` don't blow up under tests.
def _reattach_utc(target, context):
    for attr in ("created_at", "expires_at"):
        val = getattr(target, attr, None)
        if val is not None and val.tzinfo is None:
            setattr(target, attr, val.replace(tzinfo=timezone.utc))


event.listen(models.SessionToken, "load", _reattach_utc)
event.listen(models.User, "load", _reattach_utc)


@pytest.fixture(autouse=True)
def _reset_db():
    """Recreate schema before every test so each test starts clean."""
    models.Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    models.Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def client():
    # Plain TestClient (not used as a context manager) so on_startup does NOT
    # fire — its Postgres-only ALTER TABLE statements would error on SQLite.
    return TestClient(main.app)


@pytest.fixture
def db_session():
    """A raw SQLAlchemy session for tests that want to poke the DB directly."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def registered_user(client):
    """Register a fresh user and return (token, user_dict)."""
    payload = {
        "name": "Trip Tester",
        "email": "tester@example.com",
        "password": "supersecret",
    }
    r = client.post("/auth/register", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    return data["token"], data["user"]


@pytest.fixture
def auth_headers(registered_user):
    token, _ = registered_user
    return {"Authorization": f"Bearer {token}"}
