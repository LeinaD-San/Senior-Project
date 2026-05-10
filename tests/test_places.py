"""
Tests for the Google Maps proxy endpoints. We never hit Google in tests --
we replace `httpx.AsyncClient` with a fake whose `.get`/`.post` return
canned responses.
"""
import os

import pytest

import main


# ---------- httpx fake helpers ----------

class _FakeResponse:
    def __init__(self, json_data, status_code=200, text=""):
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                "boom", request=None, response=self  # type: ignore[arg-type]
            )

    def json(self):
        return self._json


class _FakeAsyncClient:
    """
    Stand-in for httpx.AsyncClient. Each instance is constructed inside
    `async with httpx.AsyncClient(...) as client:` so we implement the async
    context manager protocol. The class-level `responses` list is consumed
    in FIFO order across all instances.
    """
    responses = []  # type: list[_FakeResponse]
    last_calls = []  # type: list[tuple[str, str, dict | None]]  # (method, url, params|json)

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, **kwargs):
        type(self).last_calls.append(("GET", url, params))
        return type(self).responses.pop(0)

    async def post(self, url, headers=None, json=None, **kwargs):
        type(self).last_calls.append(("POST", url, json))
        return type(self).responses.pop(0)


@pytest.fixture
def fake_httpx(monkeypatch):
    """
    Replace `httpx.AsyncClient` with our fake for the duration of the test.
    Tests push canned responses onto `fake_httpx.responses`.
    """
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.last_calls = []
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


# ---------- /places/search ----------

def test_places_search_happy_path(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "results": [
                {
                    "place_id": "p1",
                    "name": "Best Tacos",
                    "formatted_address": "1 Main",
                    "rating": 4.7,
                    "price_level": 2,
                    "geometry": {"location": {"lat": 30.0, "lng": -97.0}},
                    "photos": [{"photo_reference": "ref-1"}],
                },
                {
                    "place_id": "p2",
                    "name": "Coffee Spot",
                    "formatted_address": "2 Main",
                    "rating": 4.4,
                    "geometry": {"location": {"lat": 30.1, "lng": -97.1}},
                    "photos": [],
                },
            ],
        })
    )

    r = client.get("/places/search", params={"q": "tacos"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"] == "tacos"
    assert body["count"] == 2
    assert body["results"][0]["place_id"] == "p1"
    # Photo URL built from photo_reference.
    assert "photo_reference=ref-1" in body["results"][0]["photo_url"]
    # No photos -> photo_url is None.
    assert body["results"][1]["photo_url"] is None


def test_places_search_500_when_no_api_key(client, fake_httpx, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    r = client.get("/places/search", params={"q": "tacos"})
    assert r.status_code == 500


def test_places_search_502_on_bad_google_status(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse(
            {"status": "REQUEST_DENIED", "error_message": "no key"}
        )
    )
    r = client.get("/places/search", params={"q": "tacos"})
    assert r.status_code == 502


def test_places_search_zero_results_returns_empty_list(client, fake_httpx):
    fake_httpx.responses.append(_FakeResponse({"status": "ZERO_RESULTS", "results": []}))
    r = client.get("/places/search", params={"q": "nothing-here"})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_places_search_validates_query_length(client):
    # min_length=1 is enforced by FastAPI; empty q -> 422.
    r = client.get("/places/search", params={"q": ""})
    assert r.status_code == 422


# ---------- /places/autocomplete ----------

def test_places_autocomplete_returns_predictions(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "predictions": [
                {
                    "description": "Austin, TX",
                    "place_id": "place-austin",
                    "structured_formatting": {
                        "main_text": "Austin",
                        "secondary_text": "TX, USA",
                    },
                }
            ],
        })
    )
    r = client.get("/places/autocomplete", params={"input": "Aus"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["predictions"][0]["place_id"] == "place-austin"
    assert body["predictions"][0]["main_text"] == "Austin"


def test_places_autocomplete_502_on_bad_status(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse({"status": "REQUEST_DENIED"})
    )
    r = client.get("/places/autocomplete", params={"input": "Aus"})
    assert r.status_code == 502


# ---------- /places/details ----------

def test_place_details_happy_path(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "result": {
                "place_id": "p1",
                "name": "X",
                "formatted_address": "1 Main",
                "rating": 4.5,
                "price_level": 2,
                "formatted_phone_number": "+1",
                "website": "https://x",
                "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                "opening_hours": {
                    "weekday_text": ["Monday: 9:00 AM – 5:00 PM"],
                    "open_now": True,
                },
                "photos": [{"photo_reference": "abc"}],
            },
        })
    )
    r = client.get("/places/details/p1")
    assert r.status_code == 200
    body = r.json()
    assert body["place_id"] == "p1"
    assert body["open_now"] is True
    assert body["hours"] == ["Monday: 9:00 AM – 5:00 PM"]
    assert len(body["photos"]) == 1
    assert "photo_reference=abc" in body["photos"][0]


def test_place_details_502_on_bad_status(client, fake_httpx):
    fake_httpx.responses.append(_FakeResponse({"status": "NOT_FOUND"}))
    r = client.get("/places/details/p1")
    assert r.status_code == 502


# ---------- /places/nearby ----------

def test_places_nearby_returns_results(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "results": [
                {
                    "place_id": "n1",
                    "name": "Nearby",
                    "vicinity": "Around here",
                    "rating": 4.0,
                    "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                }
            ],
        })
    )
    r = client.get("/places/nearby", params={"lat": 1.0, "lng": 2.0})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["results"][0]["place_id"] == "n1"
    # Address falls back to vicinity.
    assert body["results"][0]["address"] == "Around here"


# ---------- /geo/reverse ----------

def test_geo_reverse_returns_formatted_address(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "results": [{"formatted_address": "123 Test Ave, Austin, TX"}],
        })
    )
    r = client.get("/geo/reverse", params={"lat": 30.0, "lng": -97.0})
    assert r.status_code == 200
    assert r.json()["formatted_address"] == "123 Test Ave, Austin, TX"


def test_geo_reverse_handles_zero_results(client, fake_httpx):
    fake_httpx.responses.append(_FakeResponse({"status": "ZERO_RESULTS", "results": []}))
    r = client.get("/geo/reverse", params={"lat": 0.0, "lng": 0.0})
    assert r.status_code == 200
    assert r.json()["formatted_address"] is None


# ---------- /places/recommended ----------

def test_recommended_places_aggregates_per_interest(client, fake_httpx):
    # The endpoint loops over interests (one Google call per interest) and
    # returns merged + ranked results. We give the fake plenty of results to
    # consume.
    def stub_response(idx):
        return _FakeResponse({
            "status": "OK",
            "results": [
                {
                    "place_id": f"int{idx}-1",
                    "name": f"Place {idx}",
                    "formatted_address": "addr",
                    "rating": 4.5,
                    "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                }
            ],
        })

    # Up to 5 interests for solo profile -> push 5 stubs.
    for i in range(8):
        fake_httpx.responses.append(stub_response(i))

    r = client.post(
        "/places/recommended",
        json={
            "destination": "Austin",
            "limit": 10,
            "profile": {
                "group_type": "solo",
                "age_style": "adult",
                "pace": "balanced",
                "budget": "medium",
                "place_style": "mix",
                "food_focus": True,
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["destination"] == "Austin"
    assert isinstance(body["interests"], list) and body["interests"]
    assert isinstance(body["results"], list)


def test_recommended_places_400_when_destination_blank(client, fake_httpx):
    r = client.post("/places/recommended", json={"destination": "  ", "limit": 5})
    assert r.status_code == 400


# ---------- /ai/replace-stop ----------

def test_ai_replace_stop_returns_a_replacement(client, fake_httpx):
    # Two responses: search_places_for_interests, then fetch_place_details_for_scoring.
    # search returns one candidate, details returns the same place_id.
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "results": [
                {
                    "place_id": "alt1",
                    "name": "Alt Place",
                    "formatted_address": "addr",
                    "rating": 4.6,
                    "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                }
            ],
        })
    )
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "result": {
                "place_id": "alt1",
                "opening_hours": {
                    "weekday_text": ["Monday: 9:00 AM – 9:00 PM"],
                    "open_now": True,
                },
                "price_level": 2,
                "types": ["restaurant"],
                "name": "Alt Place",
                "formatted_address": "addr",
            },
        })
    )

    r = client.post(
        "/ai/replace-stop",
        json={
            "destination": "Austin",
            "interest": "food",
            "exclude_place_ids": [],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["place_id"] == "alt1"
    assert body["interest"] == "food"


def test_ai_itinerary_builds_response(client, fake_httpx):
    """
    /ai/itinerary issues two Google calls per interest (textsearch + details).
    We push enough canned OK responses for any plausible interest list and
    verify the response shape -- we don't pin the exact picks because the
    scheduler intentionally has some randomness.
    """
    def _ok_search(idx):
        return _FakeResponse({
            "status": "OK",
            "results": [
                {
                    "place_id": f"p{idx}",
                    "name": f"Place {idx}",
                    "formatted_address": "addr",
                    "rating": 4.5,
                    "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                }
            ],
        })

    def _ok_details(idx):
        return _FakeResponse({
            "status": "OK",
            "result": {
                "place_id": f"p{idx}",
                "opening_hours": {
                    "weekday_text": ["Monday: 9:00 AM – 9:00 PM"] * 7,
                    "open_now": True,
                },
                "price_level": 2,
                "types": ["restaurant"],
                "name": f"Place {idx}",
                "formatted_address": "addr",
            },
        })

    # Push plenty of canned responses (interleaved doesn't matter; both kinds
    # are dict-shaped and the endpoint pulls from the same FIFO queue).
    for i in range(40):
        fake_httpx.responses.append(_ok_search(i))
        fake_httpx.responses.append(_ok_details(i))

    r = client.post(
        "/ai/itinerary",
        json={
            "destination": "Austin",
            "days": 2,
            "interests": ["food", "coffee"],
            "profile": {
                "group_type": "solo",
                "age_style": "adult",
                "pace": "balanced",
                "budget": "medium",
                "place_style": "mix",
                "food_focus": True,
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["destination"] == "Austin"
    assert body["days"] == 2
    assert len(body["itinerary"]) == 2
    for day in body["itinerary"]:
        assert "stops" in day


def test_ai_replace_stop_404_when_all_excluded(client, fake_httpx):
    fake_httpx.responses.append(
        _FakeResponse({
            "status": "OK",
            "results": [
                {
                    "place_id": "x",
                    "name": "X",
                    "geometry": {"location": {"lat": 1.0, "lng": 2.0}},
                }
            ],
        })
    )
    r = client.post(
        "/ai/replace-stop",
        json={
            "destination": "Austin",
            "interest": "food",
            "exclude_place_ids": ["x"],
        },
    )
    assert r.status_code == 404
