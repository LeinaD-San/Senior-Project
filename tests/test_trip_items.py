"""
Tests for trip-item endpoints:
  POST   /trips/{trip_id}/items
  PATCH  /trips/{trip_id}/items/{item_id}
  DELETE /trips/{trip_id}/items/{item_id}
  PUT    /trips/{trip_id}/days/{day}/reorder
"""
import pytest


def _trip_payload(**overrides):
    base = {
        "title": "Test Trip",
        "destination": "Anywhere",
        "days": 3,
        "interests": [],
        "group_type": "solo",
        "age_style": "adult",
        "pace": "balanced",
        "budget": "medium",
        "place_style": "mix",
        "food_focus": True,
        "start_date": None,
        "notes": None,
    }
    base.update(overrides)
    return base


def _make_trip(client, auth_headers, **overrides):
    return client.post("/trips", json=_trip_payload(**overrides), headers=auth_headers).json()


def _item_payload(**overrides):
    base = {
        "day": 1,
        "place_id": "place_abc",
        "name": "Some Place",
        "notes": "",
        "category": "coffee",
        "lat": 30.27,
        "lng": -97.74,
        "address": "1 Main St",
        "rating": 4.5,
        "photo_url": None,
    }
    base.update(overrides)
    return base


# ---------- add item ----------

def test_add_trip_item_returns_item_with_position(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    r = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(),
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trip_id"] == trip["id"]
    assert body["day"] == 1
    assert body["position"] == 1


def test_add_trip_item_increments_position_per_day(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    a = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(place_id="a"), headers=auth_headers
    ).json()
    b = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(place_id="b"), headers=auth_headers
    ).json()
    c = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(place_id="c"), headers=auth_headers
    ).json()
    assert [a["position"], b["position"], c["position"]] == [1, 2, 3]


def test_add_trip_item_independent_positions_per_day(client, auth_headers):
    trip = _make_trip(client, auth_headers, days=3)
    d1 = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(day=1), headers=auth_headers
    ).json()
    d2 = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(day=2), headers=auth_headers
    ).json()
    # Each day's first item is position 1.
    assert d1["position"] == 1
    assert d2["position"] == 1


def test_add_trip_item_validates_arrival_format(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    r = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(arrival_time="9:30"),  # bad: needs HH:MM
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_add_trip_item_validates_departure_after_arrival(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    r = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(arrival_time="14:00", departure_time="13:00"),
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_add_trip_item_accepts_valid_times(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    r = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(arrival_time="09:00", departure_time="10:30"),
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["arrival_time"] == "09:00"
    assert body["departure_time"] == "10:30"


def test_add_trip_item_404_when_trip_missing(client, auth_headers):
    r = client.post(
        "/trips/999999/items", json=_item_payload(), headers=auth_headers
    )
    assert r.status_code == 404


def test_add_trip_item_403_when_not_owner(client):
    a = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@x.com", "password": "password123"},
    ).json()
    a_headers = {"Authorization": f"Bearer {a['token']}"}
    trip = _make_trip(client, a_headers)

    b = client.post(
        "/auth/register",
        json={"name": "B", "email": "b@x.com", "password": "password123"},
    ).json()
    b_headers = {"Authorization": f"Bearer {b['token']}"}

    r = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(), headers=b_headers
    )
    assert r.status_code == 403


# ---------- update item ----------

def test_update_trip_item_notes_and_completed(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    item = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(), headers=auth_headers
    ).json()

    r = client.patch(
        f"/trips/{trip['id']}/items/{item['id']}",
        json={"notes": "Try the latte", "completed": True},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["notes"] == "Try the latte"
    assert body["completed"] is True


def test_update_trip_item_validates_time_range(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    item = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(arrival_time="09:00", departure_time="10:00"),
        headers=auth_headers,
    ).json()

    r = client.patch(
        f"/trips/{trip['id']}/items/{item['id']}",
        json={"departure_time": "08:00"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_update_trip_item_changes_only_arrival(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    item = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(arrival_time="09:00", departure_time="11:00"),
        headers=auth_headers,
    ).json()

    r = client.patch(
        f"/trips/{trip['id']}/items/{item['id']}",
        json={"arrival_time": "10:00"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["arrival_time"] == "10:00"
    assert r.json()["departure_time"] == "11:00"


def test_update_trip_item_404_when_item_missing(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    r = client.patch(
        f"/trips/{trip['id']}/items/999999",
        json={"notes": "x"},
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_update_trip_item_404_when_trip_missing(client, auth_headers):
    # Trip 999999 doesn't exist.
    r = client.patch(
        "/trips/999999/items/1", json={"notes": "x"}, headers=auth_headers
    )
    assert r.status_code == 404


def test_update_trip_item_403_when_not_owner(client):
    a = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@x.com", "password": "password123"},
    ).json()
    a_headers = {"Authorization": f"Bearer {a['token']}"}
    trip = _make_trip(client, a_headers)
    item = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(), headers=a_headers
    ).json()

    b = client.post(
        "/auth/register",
        json={"name": "B", "email": "b@x.com", "password": "password123"},
    ).json()
    b_headers = {"Authorization": f"Bearer {b['token']}"}

    r = client.patch(
        f"/trips/{trip['id']}/items/{item['id']}",
        json={"notes": "x"},
        headers=b_headers,
    )
    assert r.status_code == 403


# ---------- delete item ----------

def test_delete_trip_item_removes_item(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    item = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(), headers=auth_headers
    ).json()

    r = client.delete(
        f"/trips/{trip['id']}/items/{item['id']}", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"

    # Trip GET no longer shows it.
    full = client.get(f"/trips/{trip['id']}", headers=auth_headers).json()
    assert all(i["id"] != item["id"] for i in full["items"])


def test_delete_trip_item_404_when_missing(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    r = client.delete(
        f"/trips/{trip['id']}/items/999999", headers=auth_headers
    )
    assert r.status_code == 404


def test_delete_trip_item_404_when_item_belongs_to_other_trip(client, auth_headers):
    trip_a = _make_trip(client, auth_headers, title="A")
    trip_b = _make_trip(client, auth_headers, title="B")
    item = client.post(
        f"/trips/{trip_a['id']}/items", json=_item_payload(), headers=auth_headers
    ).json()
    # Try to delete item belonging to trip_a using trip_b's URL.
    r = client.delete(
        f"/trips/{trip_b['id']}/items/{item['id']}", headers=auth_headers
    )
    assert r.status_code == 404


# ---------- reorder ----------

def test_reorder_day_items_updates_positions(client, auth_headers):
    trip = _make_trip(client, auth_headers)
    a = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(place_id="a"), headers=auth_headers
    ).json()
    b = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(place_id="b"), headers=auth_headers
    ).json()
    c = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(place_id="c"), headers=auth_headers
    ).json()

    new_order = [c["id"], a["id"], b["id"]]
    r = client.put(
        f"/trips/{trip['id']}/days/1/reorder",
        json={"ordered_item_ids": new_order},
        headers=auth_headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["id"] for i in items] == new_order
    assert [i["position"] for i in items] == [1, 2, 3]


def test_reorder_day_items_400_when_id_not_in_day(client, auth_headers):
    trip = _make_trip(client, auth_headers, days=3)
    a = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(day=1, place_id="a"),
        headers=auth_headers,
    ).json()
    # Item in day 2, not day 1.
    b_day2 = client.post(
        f"/trips/{trip['id']}/items",
        json=_item_payload(day=2, place_id="b"),
        headers=auth_headers,
    ).json()

    r = client.put(
        f"/trips/{trip['id']}/days/1/reorder",
        json={"ordered_item_ids": [a["id"], b_day2["id"]]},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_reorder_day_items_404_when_trip_missing(client, auth_headers):
    r = client.put(
        "/trips/999999/days/1/reorder",
        json={"ordered_item_ids": [1]},
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_reorder_day_items_403_when_not_owner(client):
    a_user = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@x.com", "password": "password123"},
    ).json()
    a_headers = {"Authorization": f"Bearer {a_user['token']}"}
    trip = _make_trip(client, a_headers)
    item = client.post(
        f"/trips/{trip['id']}/items", json=_item_payload(), headers=a_headers
    ).json()

    b_user = client.post(
        "/auth/register",
        json={"name": "B", "email": "b@x.com", "password": "password123"},
    ).json()
    b_headers = {"Authorization": f"Bearer {b_user['token']}"}

    r = client.put(
        f"/trips/{trip['id']}/days/1/reorder",
        json={"ordered_item_ids": [item["id"]]},
        headers=b_headers,
    )
    assert r.status_code == 403
