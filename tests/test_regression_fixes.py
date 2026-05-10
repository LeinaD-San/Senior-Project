"""
Pins the two bugs uncovered while writing the test suite:

1. models.Trip.budget had a misspelled default ("meduim"), so any Trip row
   inserted without an explicit budget value silently defaulted to a value
   that no scoring branch matches.

2. get_recommended_interests checked profile.place_style == 'tourists_spots'
   (with an extra 's'), but the frontend (planner.html) and the rest of
   main.py use 'tourist_spots'. The branch that adds museums + history
   to recommended interests therefore never fired.

Both tests fail against the buggy code and pass once the typos are fixed.
"""
import models
import main
from main import TripProfile


def test_trip_default_budget_is_medium(db_session):
    """A Trip inserted without a budget should land in the DB as 'medium'."""
    trip = models.Trip(title="t", destination="d")
    db_session.add(trip)
    db_session.commit()
    db_session.refresh(trip)
    assert trip.budget == "medium"


def test_get_recommended_interests_tourist_spots_adds_museums():
    """place_style='tourist_spots' should add 'museums' to recommended interests."""
    out = main.get_recommended_interests(
        TripProfile(group_type="solo", place_style="tourist_spots")
    )
    assert "museums" in out, (
        f"expected 'museums' in {out} when place_style='tourist_spots'"
    )
