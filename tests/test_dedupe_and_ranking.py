"""
Tests for place dedupe and ranking helpers.
"""
import main
from main import TripProfile


# ---------- dedupe_places ----------

def test_dedupe_places_removes_duplicates_by_id():
    places = [
        {"place_id": "a", "name": "A1"},
        {"place_id": "b", "name": "B1"},
        {"place_id": "a", "name": "A2"},  # duplicate id
    ]
    out = main.dedupe_places(places)
    assert [p["place_id"] for p in out] == ["a", "b"]
    # First occurrence kept.
    assert out[0]["name"] == "A1"


def test_dedupe_places_drops_entries_without_id():
    places = [
        {"place_id": "a", "name": "A"},
        {"name": "no id"},
        {"place_id": None, "name": "none id"},
    ]
    out = main.dedupe_places(places)
    assert [p["place_id"] for p in out] == ["a"]


# ---------- dedupe_places_by_id ----------

def test_dedupe_by_id_falls_back_to_name_address_when_no_id():
    places = [
        {"name": "Spot", "address": "1 Main"},
        {"name": "Spot", "address": "1 Main"},   # exact dupe
        {"name": "Spot", "address": "2 Other"},  # different address -> keep
    ]
    out = main.dedupe_places_by_id(places)
    assert len(out) == 2


def test_dedupe_by_id_skips_non_dict_entries():
    out = main.dedupe_places_by_id([{"place_id": "a"}, "garbage", None, {"place_id": "b"}])
    ids = [p.get("place_id") for p in out]
    assert ids == ["a", "b"]


def test_dedupe_by_id_handles_none_input():
    assert main.dedupe_places_by_id(None) == []


# ---------- score_place_for_profile ----------

def test_score_place_for_profile_rating_contributes():
    high = main.score_place_for_profile({"rating": 4.5}, TripProfile())
    low = main.score_place_for_profile({"rating": 2.0}, TripProfile())
    assert high > low


def test_score_place_for_profile_low_budget_penalises_expensive():
    cheap = main.score_place_for_profile(
        {"rating": 4.0, "price_level": 1}, TripProfile(budget="low")
    )
    pricey = main.score_place_for_profile(
        {"rating": 4.0, "price_level": 4}, TripProfile(budget="low")
    )
    assert cheap > pricey


def test_score_place_for_profile_interest_keyword_bonus():
    base = main.score_place_for_profile(
        {"rating": 4.0, "name": "Generic Place"},
        TripProfile(),
        interest="coffee",
    )
    coffee = main.score_place_for_profile(
        {"rating": 4.0, "name": "Joe's Espresso Cafe"},
        TripProfile(),
        interest="coffee",
    )
    assert coffee > base


# ---------- rank_places_for_profile ----------

def test_rank_places_for_profile_sorts_descending_by_score():
    places = [
        {"place_id": "a", "rating": 3.0, "name": "Plain"},
        {"place_id": "b", "rating": 4.8, "name": "Top Cafe"},
        {"place_id": "c", "rating": 4.0, "name": "Mid"},
    ]
    ranked = main.rank_places_for_profile(places, TripProfile(), interest="coffee")
    # Top-rated cafe should win.
    assert ranked[0]["place_id"] == "b"
    # Each result has a numeric score attached.
    assert all(isinstance(p["score"], (int, float)) for p in ranked)


def test_rank_places_for_profile_does_not_mutate_input():
    places = [{"place_id": "a", "rating": 3.0}]
    ranked = main.rank_places_for_profile(places, TripProfile())
    # Input dicts unchanged.
    assert "score" not in places[0]
    # Output dicts have score.
    assert "score" in ranked[0]


# ---------- score_place (extended scoring used by AI) ----------

def test_score_place_open_now_swing():
    profile = TripProfile()
    base = main.score_place({"rating": 4.0, "name": "Place"}, "food", profile)
    open_ = main.score_place(
        {"rating": 4.0, "name": "Place", "open_now": True}, "food", profile
    )
    closed = main.score_place(
        {"rating": 4.0, "name": "Place", "open_now": False}, "food", profile
    )
    assert open_ > base > closed


def test_score_place_solo_avoids_kid_focused_places():
    solo = TripProfile(group_type="solo")
    family = TripProfile(group_type="family")
    place = {"rating": 4.5, "name": "Children's Play Museum"}
    assert main.score_place(place, "museums", family) > main.score_place(
        place, "museums", solo
    )


def test_score_place_high_budget_rewards_pricey_places():
    high = TripProfile(budget="high")
    low = TripProfile(budget="low")
    place = {"rating": 4.0, "name": "Upscale Steakhouse", "price_level": 4}
    assert main.score_place(place, "food", high) > main.score_place(
        place, "food", low
    )
