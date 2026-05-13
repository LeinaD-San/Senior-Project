from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Float
from database import Base


# ======================================================
# Shared Model Helper
# ======================================================
# Returns the current UTC time for created_at fields.
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ======================================================
# User Model
# ======================================================
# Stores account identity and password hash data. Trips and session tokens connect
# back to users through user_id.
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=True)  # Nullable so older rows do not break on startup.
    email = Column(String, unique=True, nullable=False, index=True)
    password_salt = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ======================================================
# Session Token Model
# ======================================================
# Stores login tokens so the frontend can authenticate requests with
# Authorization: Bearer <token>.
class SessionToken(Base):
    __tablename__ = 'session_tokens'

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


# ======================================================
# Trip Model
# ======================================================
# Stores one saved trip. This is the trip-level data used by planner.html,
# account.html, and the AI personalization flow.
class Trip(Base):
    __tablename__ = 'trips'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    title = Column(String, nullable=False)
    destination = Column(String, nullable=False)

    # General trip setup.
    days = Column(Integer, nullable=False, default=1)

    # AI/profile settings saved with the trip so it can be reopened later.
    group_type = Column(String, nullable=False, default="solo")
    age_style = Column(String, nullable=False, default="adult")
    pace = Column(String, nullable=False, default="balanced")
    budget = Column(String, nullable=False, default="medium")
    place_style = Column(String, nullable=False, default="mix")
    food_focus = Column(Integer, nullable=False, default=1)

    # Trip-wide notes/interests/date. TripItem.notes belongs to individual stops.
    start_date = Column(String, nullable=True)
    interests_json = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    # Trip feedback for future AI personalization.
    # This is intentionally trip-level feedback, not category-level feedback,
    # so one disliked coffee shop does not mean the user dislikes all coffee shops.
    trip_rating = Column(Integer, nullable=True)
    trip_changed_from_ai = Column(Integer, nullable=True)
    trip_feedback_notes = Column(Text, nullable=True)


# ======================================================
# Trip Item Model
# ======================================================
# Stores one stop/place inside a saved trip. Trip items belong to a Trip and are
# grouped by day and ordered with position.
class TripItem(Base):
    __tablename__ = 'trip_item'

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey('trips.id'), nullable=False)

    # Day and position control where the stop appears in the itinerary notepad.
    day = Column(Integer, default=1)
    position = Column(Integer, nullable=False, default=0)

    # Google Places identity and display fields.
    place_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    notes = Column(Text, default='')
    category = Column(String, nullable=True)

    # Optional place metadata used for route optimization, details, and thumbnails.
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    address = Column(String, nullable=True)
    rating = Column(Float, nullable=True)
    photo_url = Column(Text, nullable=True)

    # Optional planned time window for open-hours warnings.
    arrival_time = Column(String, nullable=True)
    departure_time = Column(String, nullable=True)

    completed = Column(Integer, nullable=False, default=0)
