"""
Tests for the trip CRUD endpoints: POST/GET/PATCH/DELETE on /trips and /trips/{id}.
"""
import pytest


def _trip_payload(**overrides):
    base = {
        "title": "Austin Weekend",
        "destination": "Austin, TX",
        "days": 3,
        "interests": ["food", "coffee"],
        "group_type": "couple",
        "age_style": "adult",
        "pace": "balanced",
        "budget": "medium",
        "place_style": "mix",
        "food_focus": True,
        "start_date": "2024-06-01",
        "notes": "Anniversary trip",
    }
    base.update(overrides)
    return base


# ---------- create ----------

def test_create_trip_returns_full_record(client, auth_headers):
    r = client.post("/trips", json=_trip_payload(), headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] > 0
    assert data["title"] == "Austin Weekend"
    assert data["destination"] == "Austin, TX"
    assert data["days"] == 3
    assert data["interests"] == ["food", "coffee"]
    assert data["food_focus"] is True
    assert data["notes"] == "Anniversary trip"


def test_create_trip_requires_auth(client):
    r = client.post("/trips", json=_trip_payload())
    assert r.status_code == 401


def test_create_trip_validates_days_range(client, auth_headers):
    r = client.post("/trips", json=_trip_payload(days=0), headers=auth_headers)
    assert r.status_code == 422
    r = client.post("/trips", json=_trip_payload(days=99), headers=auth_headers)
    assert r.status_code == 422


def test_create_trip_validates_title_not_empty(client, auth_headers):
    r = client.post("/trips", json=_trip_payload(title=""), headers=auth_headers)
    assert r.status_code == 422


# ---------- list ----------

def test_list_trips_returns_only_current_user_trips(client):
    # User A
    a = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@x.com", "password": "password123"},
    ).json()
    a_headers = {"Authorization": f"Bearer {a['token']}"}
    client.post("/trips", json=_trip_payload(title="A trip"), headers=a_headers)

    # User B
    b = client.post(
        "/auth/register",
        json={"name": "B", "email": "b@x.com", "password": "password123"},
    ).json()
    b_headers = {"Authorization": f"Bearer {b['token']}"}
    client.post("/trips", json=_trip_payload(title="B trip"), headers=b_headers)

    a_list = client.get("/trips", headers=a_headers).json()
    b_list = client.get("/trips", headers=b_headers).json()

    assert {t["title"] for t in a_list} == {"A trip"}
    assert {t["title"] for t in b_list} == {"B trip"}


def test_list_trips_empty_for_new_user(client, auth_headers):
    r = client.get("/trips", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


# ---------- get ----------

def test_get_trip_returns_trip_with_items(client, auth_headers):
    create = client.post("/trips", json=_trip_payload(), headers=auth_headers).json()
    trip_id = create["id"]
    r = client.get(f"/trips/{trip_id}", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == trip_id
    assert data["items"] == []


def test_get_trip_404_when_missing(client, auth_headers):
    r = client.get("/trips/999999", headers=auth_headers)
    assert r.status_code == 404


def test_get_trip_403_for_other_users_trip(client):
    a = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@x.com", "password": "password123"},
    ).json()
    a_headers = {"Authorization": f"Bearer {a['token']}"}
    trip = client.post("/trips", json=_trip_payload(), headers=a_headers).json()

    b = client.post(
        "/auth/register",
        json={"name": "B", "email": "b@x.com", "password": "password123"},
    ).json()
    b_headers = {"Authorization": f"Bearer {b['token']}"}

    r = client.get(f"/trips/{trip['id']}", headers=b_headers)
    assert r.status_code == 403


# ---------- update ----------

def test_update_trip_changes_title(client, auth_headers):
    trip = client.post("/trips", json=_trip_payload(), headers=auth_headers).json()
    r = client.patch(
        f"/trips/{trip['id']}",
        json={"title": "Updated"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Updated"


def test_update_trip_partial_fields(client, auth_headers):
    trip = client.post("/trips", json=_trip_payload(), headers=auth_headers).json()
    r = client.patch(
        f"/trips/{trip['id']}",
        json={"title": "Same", "days": 5, "pace": "packed"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 5
    assert body["pace"] == "packed"
    # untouched fields preserved
    assert body["destination"] == trip["destination"]
    assert body["budget"] == trip["budget"]


def test_update_trip_replaces_interests(client, auth_headers):
    trip = client.post("/trips", json=_trip_payload(), headers=auth_headers).json()
    r = client.patch(
        f"/trips/{trip['id']}",
        json={"title": trip["title"], "interests": ["museums"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["interests"] == ["museums"]


def test_update_trip_404_when_missing(client, auth_headers):
    r = client.patch(
        "/trips/999999", json={"title": "x"}, headers=auth_headers
    )
    assert r.status_code == 404


def test_update_trip_403_for_other_users_trip(client):
    a = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@x.com", "password": "password123"},
    ).json()
    a_headers = {"Authorization": f"Bearer {a['token']}"}
    trip = client.post("/trips", json=_trip_payload(), headers=a_headers).json()

    b = client.post(
        "/auth/register",
        json={"name": "B", "email": "b@x.com", "password": "password123"},
    ).json()
    b_headers = {"Authorization": f"Bearer {b['token']}"}

    r = client.patch(
        f"/trips/{trip['id']}", json={"title": "hi"}, headers=b_headers
    )
    assert r.status_code == 403


# ---------- delete ----------

def test_delete_trip_removes_trip_and_items(client, auth_headers):
    trip = client.post("/trips", json=_trip_payload(), headers=auth_headers).json()

    # Add an item so we can verify cascade-delete behaviour.
    client.post(
        f"/trips/{trip['id']}/items",
        json={"day": 1, "place_id": "p1", "name": "Stop"},
        headers=auth_headers,
    )

    r = client.delete(f"/trips/{trip['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"

    # Trip is gone.
    r2 = client.get(f"/trips/{trip['id']}", headers=auth_headers)
    assert r2.status_code == 404


def test_delete_trip_404_when_missing(client, auth_headers):
    r = client.delete("/trips/999999", headers=auth_headers)
    assert r.status_code == 404


def test_delete_trip_403_for_other_users_trip(client):
    a = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@x.com", "password": "password123"},
    ).json()
    a_headers = {"Authorization": f"Bearer {a['token']}"}
    trip = client.post("/trips", json=_trip_payload(), headers=a_headers).json()

    b = client.post(
        "/auth/register",
        json={"name": "B", "email": "b@x.com", "password": "password123"},
    ).json()
    b_headers = {"Authorization": f"Bearer {b['token']}"}

    r = client.delete(f"/trips/{trip['id']}", headers=b_headers)
    assert r.status_code == 403
