from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Float
from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=True)#currently true so that rows do not break on startup
    email = Column(String, unique=True, nullable=False, index=True)
    password_salt = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SessionToken(Base):
    __tablename__ = 'session_tokens'

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

class Trip(Base):
    __tablename__ = 'trips'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    title= Column(String, nullable=False)
    destination = Column(String, nullable=False)

class TripItem(Base):
    __tablename__ = 'trip_item'

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey('trips.id'), nullable =False)

    day = Column(Integer, default = 1)

#this is the new position, this is implemented since there is no guaranteed order. 
#therefore position will be the order police for items within the same trip and same day. 
    position = Column(Integer, nullable=False, default =0) #added by Nick^^

    place_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    notes = Column(Text, default='')

    lat = Column(Float, nullable=True)
    lng = Column(Float,nullable=True)
    address = Column(String, nullable=True)
    rating = Column(Float, nullable=True)

    arrival_time = Column(String, nullable=True)
    departure_time = Column(String, nullable=True)

    completed = Column(Integer, nullable=False, default=0)
