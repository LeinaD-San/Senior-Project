"""
Tests for /auth/register, /auth/login, /auth/logout, and /me.
"""
from datetime import datetime, timezone, timedelta

import models


def test_register_returns_token_and_user(client):
    r = client.post(
        "/auth/register",
        json={"name": "Alice", "email": "alice@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["name"] == "Alice"
    assert "id" in body["user"]


def test_register_lowercases_email(client):
    r = client.post(
        "/auth/register",
        json={"name": "Alice", "email": "ALICE@Example.COM", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "alice@example.com"


def test_register_rejects_duplicate_email(client):
    payload = {"name": "Alice", "email": "alice@example.com", "password": "password123"}
    r1 = client.post("/auth/register", json=payload)
    assert r1.status_code == 200
    r2 = client.post("/auth/register", json=payload)
    assert r2.status_code == 400
    assert "already registered" in r2.json()["detail"].lower()


def test_register_validates_password_min_length(client):
    r = client.post(
        "/auth/register",
        json={"name": "Alice", "email": "alice@example.com", "password": "short"},
    )
    assert r.status_code == 422  # pydantic validation error


def test_login_with_valid_credentials_returns_token(client):
    client.post(
        "/auth/register",
        json={"name": "Alice", "email": "alice@example.com", "password": "password123"},
    )
    r = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["token"]


def test_login_email_is_case_insensitive(client):
    client.post(
        "/auth/register",
        json={"name": "Alice", "email": "alice@example.com", "password": "password123"},
    )
    r = client.post(
        "/auth/login",
        json={"email": "ALICE@example.com", "password": "password123"},
    )
    assert r.status_code == 200


def test_login_with_wrong_password_returns_401(client):
    client.post(
        "/auth/register",
        json={"name": "Alice", "email": "alice@example.com", "password": "password123"},
    )
    r = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "wrongpassword"},
    )
    assert r.status_code == 401


def test_login_unknown_email_returns_401(client):
    r = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "password123"},
    )
    assert r.status_code == 401


def test_me_returns_current_user(client, auth_headers, registered_user):
    _, user = registered_user
    r = client.get("/me", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == user["email"]
    assert body["id"] == user["id"]


def test_me_without_token_returns_401(client):
    r = client.get("/me")
    assert r.status_code == 401


def test_me_with_invalid_token_returns_401(client):
    r = client.get("/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_logout_invalidates_token(client, auth_headers):
    # Make sure token works first.
    assert client.get("/me", headers=auth_headers).status_code == 200

    r = client.post("/auth/logout", headers=auth_headers)
    assert r.status_code == 200

    # Token is gone, /me should now reject it.
    r2 = client.get("/me", headers=auth_headers)
    assert r2.status_code == 401


def test_logout_without_token_is_ok(client):
    # logout without auth shouldn't blow up.
    r = client.post("/auth/logout")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_expired_session_returns_401(client, auth_headers, db_session):
    # Force the session token to have expired.
    token = auth_headers["Authorization"].split(" ", 1)[1]
    sess = db_session.query(models.SessionToken).filter_by(token=token).first()
    assert sess is not None
    sess.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    r = client.get("/me", headers=auth_headers)
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()
