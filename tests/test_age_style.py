"""
Tests for age_style scoring + recommended-interests wiring.

Supported values: "kids", "young_adult", "adult" (default, no-op),
"senior". Anything else is a no-op.
"""
import main
from main import TripProfile, age_style_modifier


# ---------- age_style_modifier (the helper) ----------

def test_age_style_modifier_unknown_is_noop():
    assert age_style_modifier("a brewery downtown", None) == 0.0
    assert age_style_modifier("a brewery downtown", "") == 0.0
    assert age_style_modifier("a brewery downtown", "alien") == 0.0
    assert age_style_modifier("a brewery downtown", "adult") == 0.0


def test_age_style_modifier_kids_likes_family_places():
    assert age_style_modifier("city zoo", "kids") > 0
    assert age_style_modifier("playground at riverside park", "kids") > 0


def test_age_style_modifier_kids_dislikes_bars():
    assert age_style_modifier("downtown craft brewery", "kids") < 0
    assert age_style_modifier("the wine lounge", "kids") < 0


def test_age_style_modifier_young_adult_likes_nightlife():
    assert age_style_modifier("rooftop bar with live music", "young_adult") > 0
    assert age_style_modifier("trendy nightclub lounge", "young_adult") > 0


def test_age_style_modifier_young_adult_penalises_kid_spots():
    assert age_style_modifier("toddler indoor playground", "young_adult") < 0


def test_age_style_modifier_senior_likes_gardens_and_history():
    assert age_style_modifier("botanical garden with scenic view", "senior") > 0
    assert age_style_modifier("historic memorial monument", "senior") > 0


def test_age_style_modifier_senior_penalises_loud_venues():
    assert age_style_modifier("nightclub with loud music", "senior") < 0
    assert age_style_modifier("trampoline arcade", "senior") < 0


def test_age_style_modifier_case_insensitive():
    # We pass already-lowercased blobs in production, but the style itself
    # should be tolerant of case from the API.
    assert age_style_modifier("city zoo", "KIDS") > 0


# ---------- score_place integration ----------

def _place(name, **extra):
    base = {"name": name, "rating": 4.0, "address": ""}
    base.update(extra)
    return base


def test_score_place_kids_prefers_zoo_over_brewery():
    kids = TripProfile(group_type="family", age_style="kids")
    zoo = main.score_place(_place("Riverside Zoo"), "outdoors", kids)
    brewery = main.score_place(_place("Downtown Brewery"), "nightlife", kids)
    assert zoo > brewery


def test_score_place_young_adult_prefers_brewery_over_playground():
    ya = TripProfile(group_type="friends", age_style="young_adult")
    brewery = main.score_place(_place("Downtown Brewery"), "nightlife", ya)
    playground = main.score_place(_place("Toddler Playground"), "parks", ya)
    assert brewery > playground


def test_score_place_senior_prefers_garden_over_nightclub():
    senior = TripProfile(group_type="solo", age_style="senior")
    garden = main.score_place(_place("Botanical Garden"), "parks", senior)
    club = main.score_place(_place("Loud Nightclub"), "nightlife", senior)
    assert garden > club


def test_score_place_adult_default_unaffected():
    """The default 'adult' age_style must not change scoring vs. the previous
    behaviour, so anyone who never sets the field sees no shift."""
    adult = TripProfile(age_style="adult")
    # Verify the modifier itself contributes nothing for adult.
    assert age_style_modifier("downtown craft brewery", "adult") == 0.0
    # And that score_place still returns a finite number (sanity check).
    assert isinstance(
        main.score_place(_place("Downtown Brewery"), "nightlife", adult), float
    )


# ---------- score_place_for_profile integration ----------

def test_score_place_for_profile_respects_age_style():
    senior = TripProfile(age_style="senior")
    young = TripProfile(age_style="young_adult")
    place = _place("Botanical Garden", types=["park"])
    # Senior should score the garden higher than young_adult does.
    assert main.score_place_for_profile(place, senior, "parks") > \
           main.score_place_for_profile(place, young, "parks")


# ---------- get_recommended_interests integration ----------

def test_recommended_interests_kids_includes_parks_and_museums():
    out = main.get_recommended_interests(
        TripProfile(group_type="couple", age_style="kids")
    )
    assert "parks" in out
    assert "museums" in out


def test_recommended_interests_young_adult_includes_nightlife():
    out = main.get_recommended_interests(
        TripProfile(group_type="solo", age_style="young_adult")
    )
    assert "nightlife" in out


def test_recommended_interests_senior_includes_history():
    out = main.get_recommended_interests(
        TripProfile(group_type="couple", age_style="senior")
    )
    assert "history" in out


def test_recommended_interests_adult_unchanged():
    # Adult should match the existing baseline (no extra interests pushed in).
    adult = main.get_recommended_interests(
        TripProfile(group_type="solo", age_style="adult")
    )
    no_age = main.get_recommended_interests(TripProfile(group_type="solo"))
    assert adult == no_age
