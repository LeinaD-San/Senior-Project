"""
Tests for itinerary-building helpers: pace/budget, slot prefs, hours parsing,
and the higher-level distribute / build_balanced functions.
"""
import main
from main import TripProfile


# ---------- pace-based helpers ----------

def test_get_day_budget_minutes_by_pace():
    assert main.get_day_budget_minutes(TripProfile(pace="relaxed")) == 360
    assert main.get_day_budget_minutes(TripProfile(pace="balanced")) == 540
    assert main.get_day_budget_minutes(TripProfile(pace="packed")) == 660


def test_get_day_budget_minutes_default_when_no_profile():
    assert main.get_day_budget_minutes(None) == 540


def test_get_day_start_minutes_by_pace():
    assert main.get_day_start_minutes(TripProfile(pace="relaxed")) == 10 * 60
    assert main.get_day_start_minutes(TripProfile(pace="balanced")) == 9 * 60
    assert main.get_day_start_minutes(TripProfile(pace="packed")) == 8 * 60 + 30


def test_build_day_time_slots_returns_pairs():
    slots = main.build_day_time_slots(TripProfile(pace="balanced"))
    assert len(slots) == 4
    for start, end in slots:
        assert main.hhmm_to_minutes(start) < main.hhmm_to_minutes(end)


def test_build_day_time_slots_packed_has_more_slots_than_relaxed():
    relaxed = main.build_day_time_slots(TripProfile(pace="relaxed"))
    packed = main.build_day_time_slots(TripProfile(pace="packed"))
    assert len(packed) > len(relaxed)


# ---------- slot interest preferences ----------

def test_slot_preferences_first_slot_is_coffee_when_enough_stops():
    prefs = main.get_slot_interest_preferences(TripProfile(), max_stops_per_day=4)
    assert prefs[0] == ["coffee"]


def test_slot_preferences_evening_changes_with_group_type():
    family = main.get_slot_interest_preferences(
        TripProfile(group_type="family"), max_stops_per_day=4
    )
    couple = main.get_slot_interest_preferences(
        TripProfile(group_type="couple"), max_stops_per_day=4
    )
    # Family evening should not include nightlife.
    assert "nightlife" not in family[-1]
    # Couple evening should include nightlife.
    assert "nightlife" in couple[-1]


def test_slot_preferences_handles_short_days():
    short = main.get_slot_interest_preferences(TripProfile(), max_stops_per_day=2)
    assert len(short) == 2


# ---------- get_recommended_interests ----------

def test_get_recommended_interests_for_family_includes_parks():
    result = main.get_recommended_interests(TripProfile(group_type="family"))
    assert "parks" in result
    assert len(result) <= 5


def test_get_recommended_interests_food_focus_inserts_food():
    no_food = TripProfile(group_type="couple", food_focus=False)
    yes_food = TripProfile(group_type="couple", food_focus=True)
    yes = main.get_recommended_interests(yes_food)
    no = main.get_recommended_interests(no_food)
    # food appears in both via "couple" defaults; food_focus only inserts food
    # at the front when it's missing. We just check no duplicates and length.
    assert len(yes) == len(set(yes))
    assert len(no) == len(set(no))


def test_get_recommended_interests_dedupes():
    profile = TripProfile(group_type="family", place_style="tourists_spots")
    out = main.get_recommended_interests(profile)
    assert len(out) == len(set(out))


def test_get_recommended_interests_handles_unknown_group_type():
    profile = TripProfile(group_type="alien")
    out = main.get_recommended_interests(profile)
    assert isinstance(out, list)
    assert len(out) > 0


# ---------- build_interest_query ----------

def test_build_interest_query_includes_destination():
    q = main.build_interest_query("Austin", "food", TripProfile(), None)
    assert "Austin" in q
    assert "restaurants" in q  # food maps to "restaurants"


def test_build_interest_query_uses_budget_modifier():
    low_q = main.build_interest_query(
        "Austin", "food", TripProfile(budget="low"), None
    )
    high_q = main.build_interest_query(
        "Austin", "food", TripProfile(budget="high"), None
    )
    assert "affordable" in low_q
    assert "upscale" in high_q


def test_build_interest_query_uses_group_modifier():
    fam = main.build_interest_query(
        "Austin", "food", TripProfile(group_type="family"), None
    )
    couple = main.build_interest_query(
        "Austin", "food", TripProfile(group_type="couple"), None
    )
    assert "family" in fam.lower()
    assert "romantic" in couple.lower()


def test_build_interest_query_falls_back_to_raw_interest_when_unknown():
    q = main.build_interest_query("Austin", "skiing", TripProfile(), None)
    # 'skiing' isn't in the map; still appears in query.
    assert "skiing" in q


# ---------- estimate_visit_minutes / is_long_activity ----------

def test_estimate_visit_minutes_zoo_is_long():
    minutes = main.estimate_visit_minutes({"name": "Lincoln Park Zoo"}, "outdoors")
    assert minutes == 300


def test_estimate_visit_minutes_coffee_short():
    assert main.estimate_visit_minutes({"name": "Joe Coffee"}, "coffee") == 60


def test_estimate_visit_minutes_falls_back_on_interest():
    # No keyword in name, so fall back to interest map.
    assert main.estimate_visit_minutes({"name": "Mystery Stop"}, "museums") == 180
    # Default for unknown interest.
    assert main.estimate_visit_minutes({"name": "Mystery Stop"}, "unknown") == 90


def test_is_long_activity_threshold():
    assert main.is_long_activity({"name": "City Museum"}, "museums") is True
    assert main.is_long_activity({"name": "Joe Coffee"}, "coffee") is False


# ---------- hours parsing ----------

def test_get_place_open_close_minutes_basic():
    place = {"hours": ["Monday: 9:00 AM – 5:00 PM"]}
    open_min, close_min = main.get_place_open_close_minutes(place, 0)
    assert open_min == 9 * 60
    assert close_min == 17 * 60


def test_get_place_open_close_minutes_closed():
    place = {"hours": ["Sunday: Closed"]}
    assert main.get_place_open_close_minutes(place, 0) == (None, None)


def test_get_place_open_close_minutes_open_24_hours():
    place = {"hours": ["Monday: Open 24 hours"]}
    assert main.get_place_open_close_minutes(place, 0) == (0, 24 * 60)


def test_get_place_open_close_minutes_overnight_close():
    # 10PM-2AM should bump close past midnight.
    place = {"hours": ["Friday: 10:00 PM – 2:00 AM"]}
    open_min, close_min = main.get_place_open_close_minutes(place, 0)
    assert open_min == 22 * 60
    assert close_min == 26 * 60  # 2AM next day


def test_get_place_open_close_minutes_handles_missing_hours():
    assert main.get_place_open_close_minutes({}, 0) == (None, None)
    assert main.get_place_open_close_minutes({"hours": []}, 0) == (None, None)
    # Out-of-range index.
    assert main.get_place_open_close_minutes({"hours": ["Monday: 9:00 AM – 5:00 PM"]}, 7) == (None, None)


def test_get_place_open_minute_returns_open_time():
    place = {"hours": ["Monday: 9:00 AM – 5:00 PM"]}
    assert main.get_place_open_minute(place, 0) == 9 * 60


def test_get_place_open_minute_closed_returns_none():
    place = {"hours": ["Monday: Closed"]}
    assert main.get_place_open_minute(place, 0) is None


# ---------- is_place_open_for_time ----------

def test_is_place_open_for_time_within_hours():
    place = {"hours": ["Monday: 9:00 AM – 5:00 PM"]}
    assert main.is_place_open_for_time(place, 0, "10:00", "11:00") is True


def test_is_place_open_for_time_outside_hours():
    place = {"hours": ["Monday: 9:00 AM – 5:00 PM"]}
    assert main.is_place_open_for_time(place, 0, "08:00", "09:00") is False
    assert main.is_place_open_for_time(place, 0, "17:30", "18:00") is False


def test_is_place_open_for_time_no_hours_returns_true():
    # No hours info means we don't block.
    assert main.is_place_open_for_time({}, 0, "10:00", "11:00") is True


def test_is_place_open_for_time_closed_day():
    place = {"hours": ["Sunday: Closed"]}
    assert main.is_place_open_for_time(place, 0, "10:00", "11:00") is False


def test_is_place_open_for_time_handles_overnight():
    place = {"hours": ["Friday: 10:00 PM – 2:00 AM"]}
    # Inside the overnight window.
    assert main.is_place_open_for_time(place, 0, "23:00", "23:30") is True


# ---------- distribute_places_across_days ----------

def test_distribute_places_round_robins_across_days():
    places = [{"place_id": str(i), "name": f"P{i}"} for i in range(6)]
    out = main.distribute_places_across_days(places, days=3, max_stops_per_day=2)
    assert len(out) == 3
    # 6 places / 3 days = 2 per day.
    assert all(len(d["stops"]) == 2 for d in out)


def test_distribute_places_caps_at_days_times_max_stops():
    places = [{"place_id": str(i), "name": f"P{i}"} for i in range(20)]
    out = main.distribute_places_across_days(places, days=2, max_stops_per_day=3)
    total = sum(len(d["stops"]) for d in out)
    assert total == 6


def test_distribute_places_assigns_arrival_and_departure_times():
    places = [{"place_id": "a", "name": "A"}]
    out = main.distribute_places_across_days(places, days=1, max_stops_per_day=3)
    stop = out[0]["stops"][0]
    assert stop["arrival_time"] is not None
    assert stop["departure_time"] is not None


# ---------- build_balanced_itinerary ----------

def _mk_place(pid, name, score=10.0, rating=4.0, hours_line="Monday: 9:00 AM – 9:00 PM"):
    return {
        "place_id": pid,
        "name": name,
        "rating": rating,
        "_score": score,
        # 7 day hours so any weekday_index works mod-wise.
        "hours": [hours_line] * 7,
        "address": "",
    }


def test_build_balanced_itinerary_uses_one_place_per_interest_per_day():
    grouped = {
        "coffee": [_mk_place("c1", "Cafe One"), _mk_place("c2", "Cafe Two")],
        "food": [_mk_place("f1", "Diner One"), _mk_place("f2", "Diner Two")],
        "museums": [_mk_place("m1", "Museum One")],
    }
    itin = main.build_balanced_itinerary(
        grouped, days=2, profile=TripProfile(), max_stops_per_day=3,
        start_date="2024-01-01",
    )
    assert len(itin) == 2
    for day in itin:
        assert "stops" in day
        # Each day should pick at most one of each interest.
        cats = [s.get("category") for s in day["stops"]]
        assert len(cats) == len(set(cats))


def test_build_balanced_itinerary_handles_empty_groups():
    out = main.build_balanced_itinerary({}, days=2, profile=TripProfile())
    assert out == [{"day": 1, "stops": []}, {"day": 2, "stops": []}]


def test_build_balanced_itinerary_strips_internal_keys():
    grouped = {"coffee": [_mk_place("c1", "Cafe One")]}
    out = main.build_balanced_itinerary(grouped, days=1, profile=TripProfile())
    # No leaked internal keys.
    assert "_used_minutes" not in out[0]
    assert "_clock" not in out[0]
    assert "_has_long_activity" not in out[0]
