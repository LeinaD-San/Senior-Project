from datetime import datetime, timedelta, timezone, date
import base64
import hashlib
import hmac
import secrets

from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import List, Annotated, Optional
import os
import httpx
from dotenv import load_dotenv
import models
from database import engine, SessionLocal
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from pathlib import Path

import json
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

import re

import asyncio

import time

from typing import Optional

from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent

load_dotenv()

openai_client = OpenAI() if OpenAI and os.getenv("OPENAI_API_KEY") else None

app = FastAPI(title="Travel Agent API")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.exception_handler(OperationalError)
def sqlalchemy_operational_error_handler(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database unavailable. Start Postgres with `docker compose up -d` and verify `DATABASE_URL`.",
        },
    )


@app.get("/config/maps")
def config_maps():
    maps_key = os.getenv("GOOGLE_MAPS_JS_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    return {"google_maps_js_api_key": maps_key}


@app.get("/")
def landing_page():
    return FileResponse(BASE_DIR / "itinerary_page.html", media_type="text/html")


@app.get("/itinerary")
def itinerary_page():
    return FileResponse(BASE_DIR / 'itinerary_page.html',media_type='text/html')


@app.get("/login")
def login_page():
    return FileResponse(BASE_DIR / "login.html", media_type="text/html")

#so frontend can call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],#temp, replace later with frontend URL
    allow_credentials=False, #will change to true once the front end is done. -N
    allow_methods=["*"],
    allow_headers=["*"],
)

# creates tables
@app.on_event("startup")
def on_startup():
    try:
        models.Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trip_item ADD COLUMN IF NOT EXISTS arrival_time VARCHAR"))
            conn.execute(text("ALTER TABLE trip_item ADD COLUMN IF NOT EXISTS departure_time VARCHAR"))
            
            #This allows the existing postgres table gain the new columns without manually rebuilding the database
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS days INTEGER DEFAULT 1"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS group_type VARCHAR DEFAULT 'solo'"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS age_style VARCHAR DEFAULT 'adult'"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS pace VARCHAR DEFAULT 'balanced'"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS budget VARCHAR DEFAULT 'medium'"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS place_style VARCHAR DEFAULT 'mix'"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS food_focus INTEGER DEFAULT 1"))
            
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS start_date VARCHAR"))
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS interests_json TEXT"))
            #Adds a trip level notes reminder column
            conn.execute(text("ALTER TABLE trips ADD COLUMN IF NOT EXISTS notes TEXT"))
            #Adds a category column to each trip item.
            #This lets each stop be labled as food, coffee, parks, and museums. 
            conn.execute(text("ALTER TABLE trip_item ADD COLUMN IF NOT EXISTS category VARCHAR"))

            conn.execute(text("UPDATE users SET name = 'Traveler' WHERE name IS NULL"))
            
    except OperationalError: 
        print("ABORT ABORT, MAKE SURE YOU START WITH THE: docker compose up -d : OR ELSE THERE WILL BE ISSUES")

#DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]

#Schemas
class TripCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)

    days: int = Field(default=1, ge=1, le=14)
    interests: List[str] = []

    group_type: str = "solo"
    age_style: str = "adult"
    pace: str = "balanced"
    budget: str = "medium"
    place_style: str = "mix"
    food_focus: bool =True

    start_date: Optional[str] = None
    #optional notes or reminders for the whole trip
    notes: Optional[str] = Field(default=None, max_length=3000)


#this is so that trips can be edited later instead of creating a new one.
class TripUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    days: Optional[int] = Field(default=None, ge=1, le=14)
    interests: Optional[List[str]] = None

    group_type: Optional[str] = None
    age_style: Optional[str] = None
    pace: Optional[str] = None
    budget: Optional[str] = None
    place_style: Optional[str] = None
    food_focus: Optional[bool] = None

    start_date: Optional[str] = None

    notes: Optional[str] = Field(default=None, max_length=3000)


class RegisterPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)

class LoginPayload(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)

class SessionResponse(BaseModel):
    token: str
    user: dict

class TripItemCreate(BaseModel):
    day: int = Field(ge=1, le=30)
    place_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=1000)
    #Category tells the frontend what type of stop this is.
    category: Optional[str] = Field(default=None, max_length=50)

    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    rating: Optional[float] = None

    arrival_time: Optional[str] = Field(default=None, max_length=5)
    departure_time: Optional[str] = Field(default=None, max_length=5)


class TripItemUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=1000)
    completed: Optional[bool] = None
    arrival_time: Optional[str] = Field(default=None, max_length=5)
    departure_time: Optional[str] = Field(default=None, max_length=5)
    #allows the category of an existing stop to be edited. 
    category: Optional[str] = Field(default=None, max_length=50)

class TripProfile(BaseModel):
    group_type: str = 'solo'
    age_style: str = 'adult'
    pace: str = 'balanced'
    budget: str = 'medium'
    place_style: str = 'mix'
    food_focus: bool = True

class recommendedPlacesRequest(BaseModel):
    destination: str
    profile: Optional[TripProfile] = None
    limit: int = 24

class ItineraryRequest(BaseModel):
    destination: str = Field(min_length=1,max_length=120)
    days: int= Field(ge=1, le=14)
    interests: List[str] = []
    profile: Optional[TripProfile] = None
    start_date: Optional[str] = None
    template_description: Optional[str] = None


#AI classes will give the backend a clean response format
class AIStop(BaseModel):
    place_id: str
    name: str
    category: Optional[str] = None
    address: str = ""
    rating: Optional[float] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    arrival_time: Optional[str] = None
    departure_time: Optional[str] = None
    suggestion_note: Optional[str] = None
    
class AIDay(BaseModel):
    day: int
    stops: List[AIStop]

class AIItineraryResponse(BaseModel):
    destination: str
    days: int
    itinerary: list[AIDay]

class ReorderPayload(BaseModel):
    ordered_item_ids: List[int] = Field(min_length=1)

class ReplaceStopRequest(BaseModel):
    destination: str
    interest: str
    exclude_place_ids: List[str] = []
    profile: Optional[TripProfile] = None




AI_OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "destination": {"type": "string"},
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer"},
                    "theme": {"type": "string"},
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                        "maxItems": 3
                    }
                },
                "required": ["day", "theme", "queries"],
                "additionalProperties": False
            }
        }
    },
    "required": ["destination", "days"],
    "additionalProperties": False
}


#app Health/activity
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/ai/test")
def ai_test():
    if not openai_client:
        raise HTTPException(status_code=503, detail="AI not configured")
    try: 
        response = openai_client.responses.create(
            model= "gpt-5-mini",
            input= "Say hello in one short sentence." 
        )
        return {"ok": True, "text": response.output_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _hash_password(password: str, salt_b64: str) -> str:
    salt = base64.b64decode(salt_b64.encode("utf-8"))
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return base64.b64encode(dk).decode("utf-8")

#these will be some general backend helpers
def _new_salt_b64() -> str:
    return base64.b64encode(secrets.token_bytes(16)).decode("utf-8")

def _encode_interests(interests: List[str]) -> str:
    return json.dumps(interests or [])

def _decode_interests(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try: 
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
        return []
    except Exception: 
        return []

#This helper will protect the app from broken times before it goes through the database
def validate_hhmm(value: Optional[str]) -> Optional[str]:
    # if the user did not provide a time, that is fine
    if value is None or value == "":
        return value
    #makes sure the time looks like exactly to digits, colon, two digits.
    if not re.match(r"^\d{2}:\d{2}$", value):
        raise HTTPException(
            status_code=400,
            detail="Time must use HH:MM format, for example 09:30 or 14:00.",
        )

    hour_text, minute_text = value.split(":")
    hour = int(hour_text)
    minute = int(minute_text)

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise HTTPException(
            status_code=400,
            detail="Time must be a valid 24-hour time."
        )

    return value

def validate_time_range(
    arrival_time: Optional[str],
    departure_time: Optional[str],
) -> None:

    if not arrival_time or not departure_time:
        return
    
    arrival_minutes = hhmm_to_minutes(arrival_time)
    departure_minutes = hhmm_to_minutes(departure_time)

    if departure_minutes <= arrival_minutes:
        raise HTTPException(
            status_code=400,
            detail="Departure time must be after arrival time.",
        )

def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def get_current_user(
    db: db_dependency,
    authorization: str | None = Header(default=None),
) -> models.User:
    token = _parse_bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    now = datetime.now(timezone.utc)
    session = (
        db.query(models.SessionToken)
        .filter(models.SessionToken.token == token)
        .first()
    )
    if not session or session.expires_at <= now:
        raise HTTPException(status_code=401, detail="Session expired")

    user = db.get(models.User, session.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user


@app.post("/auth/register", response_model=SessionResponse)
def auth_register(payload: RegisterPayload, db: db_dependency):
    existing = db.query(models.User).filter(models.User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    salt_b64 = _new_salt_b64()
    password_hash = _hash_password(payload.password, salt_b64)
    user = models.User(
        name=payload.name.strip(),
        email=payload.email.lower(), 
        password_salt=salt_b64, 
        password_hash=password_hash
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = secrets.token_urlsafe(32)
    session = models.SessionToken(
        token=token,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(session)
    db.commit()

    return {"token": token,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
            },
        }


@app.post("/auth/login", response_model=SessionResponse)
def auth_login(payload: LoginPayload, db: db_dependency):
    user = db.query(models.User).filter(models.User.email == payload.email.lower()).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    expected = _hash_password(payload.password, user.password_salt)
    if not hmac.compare_digest(expected, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = secrets.token_urlsafe(32)
    session = models.SessionToken(
        token=token,
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(session)
    db.commit()
    return {"token": token,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
            },
        }


@app.post("/auth/logout")
def auth_logout(db: db_dependency, authorization: str | None = Header(default=None)):
    token = _parse_bearer(authorization)
    if not token:
        return {"status": "ok"}

    db.query(models.SessionToken).filter(models.SessionToken.token == token).delete()
    db.commit()
    return {"status": "ok"}


@app.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return {"id": user.id, "name": user.name, "email": user.email}

#DB--Trips
@app.post("/trips")
def create_trip(payload: TripCreate, db: db_dependency, user: models.User = Depends(get_current_user)):
    trip = models.Trip(
        user_id=user.id,
        title=payload.title,
        destination=payload.destination,
        days=payload.days,
        group_type=payload.group_type,
        age_style=payload.age_style,
        pace=payload.pace,
        budget=payload.budget,
        place_style=payload.place_style,
        food_focus=1 if payload.food_focus else 0,
        start_date=payload.start_date,
        interests_json=_encode_interests(payload.interests),
        notes=payload.notes,
        )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return {
        "id": trip.id,
        "title": trip.title, 
        "destination": trip.destination,
        "days": trip.days,
        "interests": _decode_interests(trip.interests_json),
        "group_type": trip.group_type,
        "age_style": trip.age_style,
        "pace": trip.pace,
        "budget": trip.budget,
        "place_style": trip.place_style,
        "food_focus": bool(trip.food_focus),
        "start_date": trip.start_date,
        "notes": trip.notes,
        }


@app.get("/trips")
def list_trips(db: db_dependency, user: models.User = Depends(get_current_user)):
    trips = db.query(models.Trip).filter(models.Trip.user_id == user.id).all()
    return [
        {
            "id": t.id, 
            "title": t.title, 
            "destination": t.destination,
            "days": t.days,
            "interests": _decode_interests(t.interests_json),
            "group_type": t.group_type,
            "age_style": t.age_style,
            "pace": t.pace,
            "budget": t.budget,
            "place_style": t.place_style,
            "food_focus": bool(t.food_focus),
            "start_date": t.start_date,
            "notes": t.notes,
        }
        for t in trips
    ]


@app.patch("/trips/{trip_id}")
def update_trip(trip_id: int, payload: TripUpdate, db: db_dependency, user: models.User = Depends(get_current_user)):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    trip.title = payload.title

    if payload.days is not None:
        trip.days = payload.days
    if payload.interests is not None:
        trip.interests_json = _encode_interests(payload.interests)
    if payload.group_type is not None:
        trip.group_type = payload.group_type
    if payload.age_style is not None:
        trip.age_style = payload.age_style
    if payload.pace is not None:
        trip.pace = payload.pace
    if payload.budget is not None:
        trip.budget = payload.budget
    if payload.place_style is not None:
        trip.place_style = payload.place_style
    if payload.food_focus is not None:
        trip.food_focus = 1 if payload.food_focus else 0
    if payload.start_date is not None:
        trip.start_date = payload.start_date
    if payload.notes is not None:
        trip.notes = payload.notes

    db.commit()
    db.refresh(trip)
    return {
        "id": trip.id, 
        "title": trip.title, 
        "destination": trip.destination,
        "days": trip.days,
        "interests": _decode_interests(trip.interests_json),
        "group_type": trip.group_type,
        "age_style": trip.age_style,
        "pace": trip.pace,
        "budget": trip.budget,
        "place_style": trip.place_style,
        "food_focus": bool(trip.food_focus),
        "start_date": trip.start_date,
        "notes": trip.notes,
        }


@app.post("/trips/{trip_id}/items")
def add_trip_item(trip_id: int, payload: TripItemCreate, db: db_dependency, user: models.User = Depends(get_current_user)):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    #this is added to assist with the positioning of the items
    last_pos = (
        db.query(models.TripItem.position)
        .filter(models.TripItem.trip_id == trip_id, models.TripItem.day == payload.day)
        .order_by(models.TripItem.position.desc())
        .limit(1)
        .scalar()
    )

    next_pos = (last_pos + 1) if last_pos is not None else 1
    #validate arrival and departure times before saving.
    arrival_time = validate_hhmm(payload.arrival_time)
    departure_time = validate_hhmm(payload.departure_time)

    #makes sure the departure time comes after the arrival time.
    validate_time_range(arrival_time, departure_time)

    #we will use position=next_pos when creating the item. 

    item = models.TripItem(
        trip_id=trip_id,
        day=payload.day,
        position=next_pos,
        place_id=payload.place_id,
        name=payload.name,
        category=payload.category,
        notes=payload.notes,
        lat= payload.lat,
        lng=payload.lng,
        address =payload.address,
        rating=payload.rating,
        arrival_time=arrival_time,
        departure_time=departure_time,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "trip_id": item.trip_id,
        "day": item.day,
        "position": item.position,
        "place_id": item.place_id,
        "name": item.name,
        "notes": item.notes,
        "category": item.category,
        "completed": bool(item.completed),
        "lat": item.lat,
        "lng": item.lng,
        "address": item.address,
        "rating": item.rating,
        "arrival_time": item.arrival_time,
        "departure_time": item.departure_time,
    }


@app.get("/trips/{trip_id}")
def get_trip(trip_id: int, db: db_dependency, user: models.User = Depends(get_current_user)):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    if trip.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    items = (
        db.query(models.TripItem)
        .filter(models.TripItem.trip_id == trip_id)
        .order_by(models.TripItem.day.asc(), models.TripItem.position.asc())
        .all()
    )
    return {
        "id": trip.id,
        "title": trip.title,
        "destination": trip.destination,
        "days": trip.days,
        "interests": _decode_interests(trip.interests_json),
        "group_type": trip.group_type,
        "age_style": trip.age_style,
        "pace": trip.pace,
        "budget": trip.budget,
        "place_style": trip.place_style,
        "food_focus": bool(trip.food_focus),
        "start_date": trip.start_date,
        "notes": trip.notes,
        "items": [
            {
                "id": i.id,
                "day": i.day,
                "position": i.position,
                "place_id": i.place_id,
                "name": i.name,
                "notes": i.notes,
                "category": i.category,
                "completed": bool(i.completed),
                "lat": i.lat,
                "lng": i.lng,
                "address": i.address,
                "rating": i.rating,
                "arrival_time": i.arrival_time,
                "departure_time": i.departure_time,
            }
            for i in items
        ],
    }

@app.delete('/trips/{trip_id}')
def delete_trip(trip_id: int, db: db_dependency, user: models.User = Depends(get_current_user)):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail = 'Trip not found')
    if trip.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    #delete child items first to avoid fk issues.
    db.query(models.TripItem).filter(models.TripItem.trip_id == trip_id).delete()
    db.delete(trip)
    db.commit()
    return {'status': 'deleted', 'trip_id':trip_id}

@app.delete('/trips/{trip_id}/items/{item_id}')
def delete_trip_item(trip_id: int, item_id: int, db: db_dependency, user: models.User = Depends(get_current_user)):
    item = db.get(models.TripItem, item_id)

    if not item or item.trip_id != trip_id:
        raise HTTPException(status_code=404, detail='Item not found')

    trip = db.get(models.Trip, trip_id)
    if not trip or trip.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    
    db.delete(item)
    db.commit()
    return{'status': 'deleted', 'item_id':item_id}


@app.patch('/trips/{trip_id}/items/{item_id}')
def update_trip_item(
    trip_id: int,
    item_id: int,
    payload: TripItemUpdate,
    db: db_dependency,
    user: models.User = Depends(get_current_user),
):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail='Trip not found')
    if trip.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    item = db.get(models.TripItem, item_id)
    if not item or item.trip_id != trip_id:
        raise HTTPException(status_code=404, detail='Item not found')

    updates = payload.model_dump(exclude_unset=True)
    if 'notes' in updates:
        item.notes = updates['notes']
    if 'category' in updates:
        item.category = updates['category']
    if 'completed' in updates:
        item.completed = 1 if updates['completed'] else 0

    new_arrival_time = item.arrival_time
    new_departure_time = item.departure_time

    if 'arrival_time' in updates:
        new_arrival_time = validate_hhmm(updates['arrival_time'])
    if 'departure_time' in updates:
        new_departure_time = validate_hhmm(updates['departure_time'])

    #makes sure departure is still after arrival after the update
    validate_time_range(new_arrival_time, new_departure_time)

    item.arrival_time = new_arrival_time
    item.departure_time = new_departure_time

    db.commit()
    db.refresh(item)
    return {
        'id': item.id,
        'trip_id': item.trip_id,
        'day': item.day,
        'position': item.position,
        'place_id': item.place_id,
        'name': item.name,
        'notes': item.notes,
        'category': item.category,
        'completed': bool(item.completed),
        'arrival_time': item.arrival_time,
        'departure_time': item.departure_time,
    }

@app.put("/trips/{trip_id}/days/{day}/reorder")
def reorder_day_items(
    trip_id: int,
    day: int,
    payload: ReorderPayload,
    db: db_dependency,
    user: models.User = Depends(get_current_user),
):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail='Trip not found')
    if trip.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    items = (
        db.query(models.TripItem)
        .filter(models.TripItem.trip_id == trip_id, models.TripItem.day == day)
        .all()
    )
    items_by_id = {i.id: i for i in items}

    for item_id in payload.ordered_item_ids:
        if item_id not in items_by_id:
            raise HTTPException(status_code=400, detail=f'Item {item_id} not found in this trip/day')

    for idx, item_id in enumerate(payload.ordered_item_ids, start=1):
        items_by_id[item_id].position = idx

    db.commit()

    updated = (
        db.query(models.TripItem)
        .filter(models.TripItem.trip_id == trip_id, models.TripItem.day == day)
        .order_by(models.TripItem.position.asc())
        .all()
    )
    return {
        'trip_id': trip_id,
        'day': day,
        'items': [
            {"id": i.id,
             "position": i.position,
             "place_id": i.place_id,
             "name": i.name,
             "notes": i.notes,
             "category": i.category,
             }
            for i in updated
        ],
    } 

#trip notepad
@app.get("/planner")
def planner_page():
    return FileResponse(BASE_DIR / "planner.html", media_type="text/html")


#account
@app.get("/account")
def account_page():
    return FileResponse(BASE_DIR / "account.html", media_type="text/html")   


#Google Maps
'''
@app.get("/places/search")
async def places_search(q: str, lat: Optional[float] = None, lng: Optional[float] = None, radius: int = 30000):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is not set")

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": q, "key": api_key}

    if lat is not None and lng is not None:
        params["location"] = f"{lat},{lng}"
        params["radius"] = str(radius)

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(status_code=502, detail={"google_status": status, "error": data.get("error_message")})

    results = []
    for p in data.get("results", []):

        location = p.get('geometry', {}).get('location',{})
        results.append({
            "place_id": p.get("place_id"),
            "name": p.get("name"),
            "address": p.get("formatted_address"),
            "rating": p.get("rating"),
            'lat':location.get('lat'),
            'lng':location.get('lng')
        })

    return {"query": q, "count": len(results), "results": results}

'''

def get_real_weekday_index(start_date_str: str | None, day_offset: int) -> int:
    if start_date_str:
        try:
            trip_start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            trip_start = datetime.now().date()
    else:
        trip_start = datetime.now().date()
    target_day = trip_start + timedelta(days = day_offset)
    return target_day.weekday()

def estimate_price_score(place: dict) -> int:
    price_level = place.get('price_level')
    if isinstance(price_level, int):
        mapping = {
            0:1,
            1:3,
            2:5,
            3:7,
            4:9,
        }
        return mapping.get(price_level, 5)
    name = (place.get('name') or '').lower()
    address = (place.get('formatted_address') or place.get('address') or '').lower()
    text_blob = f'{name} {address}'

    high_keywords = ["steakhouse", "fine dining", "luxury", "resort", "upscale", "wine bar"]
    medium_keywords = ["restaurant", "brunch", "bistro", "shopping", "grill", "bar", "cafe"]
    low_keywords = ["park", "museum", "trail", "coffee", "bookstore", "historic", "garden"]

    if any(word in text_blob for word in high_keywords):
        return 8
    if any(word in text_blob for word in medium_keywords):
        return 5
    if any(word in text_blob for word in low_keywords):
        return 3
    return 5


@app.get("/places/search")
async def places_search(
    q: str = Query(min_length=1, max_length=120),
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius: int = 30000
):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is not set")

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": q, "key": api_key}

    if lat is not None and lng is not None:
        params["location"] = f"{lat},{lng}"
        params["radius"] = str(radius)

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(
            status_code=502,
            detail={"google_status": status, "error": data.get("error_message")},
        )

    results = []
    for p in data.get("results", []):
        location = p.get("geometry", {}).get("location", {})

        # Build a thumbnail URL if Google returned a photo_reference
        raw_photos = p.get("photos", [])
        photo_urls = []
        for ph in raw_photos[:5]:
            ref = ph.get("photo_reference")
            if ref:
                photo_urls.append(
                "https://maps.googleapis.com/maps/api/place/photo"
                f"?maxwidth=400&photo_reference={ref}&key={api_key}"
            )

        results.append({
            "place_id": p.get("place_id"),
            "name": p.get("name"),
            "address": p.get("formatted_address"),
            "rating": p.get("rating"),
            "price_level": p.get('price_level'),
            "price_estimate": estimate_price_score(p),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
            "photo_url": photo_urls[0] if raw_photos else None,
            "photos": photo_urls,
        })

    return {"query": q, "count": len(results), "results": results}

@app.post('/places/recommended')
async def recommended_places(payload: recommendedPlacesRequest):
    destination = payload.destination.strip()

    if not destination:
        raise HTTPException(status_code=400, detail="Destination is required")

    profile = payload.profile or TripProfile()
    interests = get_recommended_interests(profile)

    grouped_results = []

    for interest in interests:
        try:
            places = await search_places_for_interests(
                destination = destination,
                interest = interest,
                profile = profile,
                template_description=None,
            )

            places = rank_places_for_profile(
                places=places,
                profile=profile,
                interest=interest,
            )
            grouped_results.append(places)
        except Exception as e:
            print(f'recommended_places error for{interest}:', repr(e))
            grouped_results.append([])
    
    merged = []
    max_len = max((len(group) for group in grouped_results), default=0)

    for i in range(max_len):
        for group in grouped_results:
            if i < len(group):
                merged.append(group[i])

    unique = dedupe_places_by_id(merged)
    ranked = rank_places_for_profile(unique, profile)

    return {
        "destination": destination,
        "interests": interests,
        "results": ranked[:max(1, min(payload.limit, 60))],
    }


@app.get("/places/autocomplete")
async def places_autocomplete(
    input: str = Query(min_length=1, max_length=120),
    types: Optional[str] = None,
):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is not set")

    url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
    params = {
        "input": input,
        "key": api_key,
    }
    if types:
        params["types"] = types
    async with httpx.AsyncClient(timeout=15)as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data= r.json()
    status = data.get('status')
    if status not in ('OK', "ZERO_RESULTS"):
        raise HTTPException(
            status_code=502,
            detail={"google_status": status, 'error': data.get('error_message')},
        )
        
    predictions = []
    for p in data.get('predictions',[]):
        predictions.append({
            'description': p.get('description'),
            'place_id':p.get('place_id'),
            'main_text':(p.get('structured_formatting') or {}).get('main_text'),
            'secondary_text': (p.get('structured_formatting') or {}).get('secondary_text'),
        })
    return {'count': len(predictions), 'predictions': predictions}

@app.get('/places/details/{place_id}')
async def place_details(place_id:str):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")

    if not api_key:
        raise HTTPException(status_code=500, detail='GOOGLE_MAPS_API_KEY not set')

    url = 'https://maps.googleapis.com/maps/api/place/details/json'

    params = {
        'place_id':place_id,
        'key': api_key,
        'fields': ','.join([
            'place_id',
            'name',
            'formatted_address',
            'formatted_phone_number',
            'website',
            'rating',
            'price_level',
            'opening_hours',
            'geometry',
            'photos',
        ])
    }

    async with httpx.AsyncClient(timeout=15)as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    status = data.get('status')
    if status != 'OK':
        raise HTTPException(
            status_code=502,
            detail = {'google_status': status, 'error': data.get('error_message')}
        )

    place = data.get('result',{})
    location = place.get('geometry', {}).get('location',{})

    photos = []
    for p in place.get('photos',[])[:8]:
        ref = p.get('photo_reference')
        if ref:
            photos.append(
                f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=1200&photo_reference={ref}&key={api_key}"
            )
    return {
        "place_id": place.get("place_id"),
        "name": place.get("name"),
        "address": place.get("formatted_address"),
        "rating": place.get("rating"),
        "price_level": place.get('price_level'),
        "phone": place.get("formatted_phone_number"),
        "website": place.get("website"),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
        "hours": (place.get("opening_hours") or {}).get("weekday_text", []),
        "open_now": (place.get("opening_hours") or {}).get("open_now", None),
        "photos": photos,
    }


@app.get("/places/nearby")
async def places_nearby(
    lat: float,
    lng: float,
    keyword: Optional[str] = None,
    radius: int = 3000,
):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is not set")

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": str(radius),
        "key": api_key,
    }
    if keyword:
        params["keyword"] = keyword

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(status_code=502, detail={"google_status": status, "error": data.get("error_message")})

    results = []
    for p in data.get("results", []):
        location = p.get("geometry", {}).get("location", {})
        results.append(
            {
                "place_id": p.get("place_id"),
                "name": p.get("name"),
                "address": p.get("vicinity") or p.get("formatted_address"),
                "rating": p.get("rating"),
                "lat": location.get("lat"),
                "lng": location.get("lng"),
            }
        )

    return {"count": len(results), "results": results}


@app.get("/geo/reverse")
async def geo_reverse(lat: float, lng: float):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is not set")

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lng}", "key": api_key}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(status_code=502, detail={"google_status": status, "error": data.get("error_message")})

    first = (data.get("results") or [{}])[0]
    return {"formatted_address": first.get("formatted_address")}

#this is a helper that maps interests to search terms
INTEREST_QUERY_MAP = {
    "food": "restaurants",
    "coffee": "coffee shops",
    "parks": "parks",
    "museums": "museums",
    "nightlife": "bars nightlife",
    "shopping": "shopping malls markets bookstores mixed retail",
    "outdoors": "outdoor attractions",
    "history": "historic sites",
}

RECOMMENDED_INTERESTS_BY_PROFILE = {
    "family": ["parks", "food", "museums", "shopping"],
    "couple": ["coffee", "food", "history", "nightlife"],
    "friends": ["food", "nightlife", "shopping", "outdoors"],
    "solo": ["coffee", "history", "parks", "food"],
}

DEFAULT_RECOMMENDED_INTERESTS = [
    "food",
    "coffee",
    "parks",
    "museums",
    "history",
    "shopping",
    "outdoors",
    "nightlife",
]

def get_recommended_interests(profile: Optional[TripProfile]) -> list[str]:
    profile = profile or TripProfile()

    interests = list(
        RECOMMENDED_INTERESTS_BY_PROFILE.get(
            profile.group_type,
            DEFAULT_RECOMMENDED_INTERESTS[:4],
        )
    )

    if profile.food_focus and "food" not in interests:
        interests.insert(0, 'food')

    if profile.place_style == 'hidden_gems':
        interests.append('history')
        interests.append('coffee')

    if profile.place_style =='tourists_spots':
        interests.append('museums')
        interests.append('history')
    seen = set()
    cleaned = []
    for interest in interests:
        if interest not in seen:
            seen.add(interest)
            cleaned.append(interest)
    return cleaned[:5]

def build_interest_query(
    destination: str,
    interest: str,
    profile: Optional[TripProfile],
    template_description: Optional[str],
) -> str:
    search_term = INTEREST_QUERY_MAP.get(interest, interest)
    profile = profile or TripProfile()

    modifiers: list[str] = []

    if profile.budget == "low":
        modifiers.append("affordable budget friendly")
    elif profile.budget == "medium":
        modifiers.append("moderately priced casual nice")
    elif profile.budget == "high":
        modifiers.append("upscale premium")

    if profile.place_style == "hidden_gems":
        modifiers.append("local hidden gems")
    elif profile.place_style == "tourist_spots":
        modifiers.append("popular tourist spots")

    if profile.group_type == "family":
        modifiers.append("family friendly kid friendly")
    elif profile.group_type == "couple":
        modifiers.append("romantic date night scenic")
    elif profile.group_type == "friends":
        modifiers.append("group fun social lively")
    elif profile.group_type == "solo":
        modifiers.append("solo friendly relaxed independent")

    if interest == "shopping" and profile.group_type in ("solo", "couple", "friends"):
        modifiers.append("general shopping mixed retail unisex")
    elif interest == "shopping" and profile.group_type == "family":
        modifiers.append("family friendly shopping")

    if profile.food_focus and interest in ("food", "coffee"):
        modifiers.append("popular local must try")

    modifier_text = " ".join(m for m in modifiers if m).strip()
    if modifier_text:
        return f"{modifier_text} {search_term} in {destination}"
    return f"{search_term} in {destination}"

#will give us real place candidates from google. 
async def search_places_for_interests(
    destination: str,
    interest: str,
    profile: Optional[TripProfile] = None,
    template_description: Optional[str] = None,
) -> List[dict]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is not set")

    query = build_interest_query(destination, interest, profile, template_description)

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": query, "key": api_key}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
    
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise HTTPException(
            status_code=502,
            detail={"google_status": status, "error": data.get("error_message")}
        )

    results = []
    for p in data.get("results", [])[:12]:
        location = p.get("geometry",{}).get("location", {})
        results.append({
            "place_id": p.get("place_id"),
            "name": p.get("name"),
            "address": p.get("formatted_address"),
            "rating": p.get("rating"),
            'price_level':p.get('price_level'),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
        })
    return results

def dedupe_places(places: List[dict]) -> List[dict]:
    seen = set()
    deduped = []

    for p in places: 
        place_id = p.get("place_id")
        if not place_id or place_id in seen:
            continue
        seen.add(place_id)
        deduped.append(p)
    return deduped

def dedupe_places_by_id(places: list[dict]) -> list[dict]:
    seen = set()
    unique = []

    for place in places or []:
        if not isinstance(place, dict):
            continue

        place_id = place.get("place_id")
        fallback_key = f"{place.get('name', '')}|{place.get('address', '')}"

        key = place_id or fallback_key
        if not key or key in seen:
            continue

        seen.add(key)
        unique.append(place)

    return unique

def score_place_for_profile(place: dict, profile: Optional[TripProfile] = None, interest: Optional[str]=None) -> float:
    profile = profile or TripProfile()

    score = 0.0

    rating = place.get('rating')
    if isinstance(rating, (int, float)):
        score += rating * 10

    user_ratings_total = place.get('user_rating_total') or place.get('reviews') or 0
    if isinstance(user_ratings_total, (int, float)):
        score += min(user_ratings_total, 1000)/100
    price_level = place.get('price_level')

    if profile.budget == 'low':
        if price_level in (0,1,2, None):
            score += 8
        elif price_level in (3,4):
            score -= 8
        
    elif profile.budget == 'medium':
        if price_level in (1,2,None):
            score += 5
        elif price_level == 4:
            score -= 4
    
    elif profile.budget == 'high':
        if price_level in (2,3,4):
            score += 5
    
    name = str(place.get('name') or '').lower()
    address = str(place.get('address') or '').lower()
    types = ' '.join(place.get('types') or []).lower()
    blob = f'{name} {address} {types}'

    if interest:
        interest = interest.lower()

        if interest == "coffee" and any(word in blob for word in ["coffee", "cafe", "espresso"]):
            score += 10

        if interest == "food" and any(word in blob for word in ["restaurant", "food", "grill", "kitchen", "taqueria", "cafe"]):
            score += 10

        if interest == "parks" and any(word in blob for word in ["park", "garden", "nature", "trail"]):
            score += 10

        if interest == "museums" and any(word in blob for word in ["museum", "gallery", "art", "exhibit"]):
            score += 10

        if interest == "history" and any(word in blob for word in ["heritage", "historic", "history", "museum", "landmark"]):
            score += 10

        if interest == "nightlife" and any(word in blob for word in ["bar", "lounge", "brewery", "nightclub"]):
            score += 10

        if interest == "shopping" and any(word in blob for word in ["mall", "market", "shop", "store", "boutique"]):
            score += 10

        if interest == "outdoors" and any(word in blob for word in ["outdoor", "trail", "nature", "park", "garden"]):
            score += 10

        if profile.food_focus and any(word in blob for word in ["restaurant", "food", "cafe", "coffee", "grill", "kitchen"]):
            score += 4

    return score

def rank_places_for_profile(
    places: list[dict],
    profile: Optional[TripProfile] = None, 
    interest: Optional[str] = None,
) -> list[dict]:
    ranked = []

    for place in places:
        place_copy = dict(place)
        place_copy['score'] = round(score_place_for_profile(place_copy, profile, interest),2)
        ranked.append(place_copy)

    ranked.sort(
        key=lambda p: (
            p.get('score', 0),
            p.get('rating') or 0,
        ),
        reverse=True,
    )
    return ranked



@app.post("/ai/replace-stop")
async def ai_replace_stop(body: ReplaceStopRequest):
    profile = body.profile or TripProfile()

    results = await search_places_for_interests(body.destination, body.interest, profile)

    ranked = []
    excluded = set(body.exclude_place_ids or [])

    for place in results:
        pid = place.get("place_id")
        if not pid or pid in excluded:
            continue

        details = await fetch_place_details_for_scoring(pid)
        if details:
            place.update(details)

        place["_interest"] = body.interest
        place["_score"] = score_place(place, body.interest, profile)
        ranked.append(place)

    ranked.sort(key=lambda p: p["_score"], reverse=True)

    if not ranked:
        raise HTTPException(status_code=404, detail="No replacement found")

    top_pool = ranked[:5] if len(ranked) >= 5 else ranked
    best = secrets.choice(top_pool)

    return {
        "place_id": best.get("place_id"),
        "name": best.get("name"),
        "address": best.get("address") or "",
        "rating": best.get("rating"),
        "lat": best.get("lat"),
        "lng": best.get("lng"),
        "interest": body.interest,
    }

def score_place(place: dict, interest: str, profile: Optional[TripProfile]) -> float:
    profile = profile or TripProfile()
    score = 0.0

    rating = place.get("rating")
    if isinstance(rating, (int, float)):
        score += float(rating) * 10

    price_level = place.get("price_level")

    open_now = place.get("open_now")
    if open_now is False:
        score -= 35
    elif open_now is True:
        score += 8

    name = (place.get("name") or "").lower()
    address = (place.get("address") or "").lower()
    text_blob = f"{name} {address}"

    kid_keywords = [
        "kids", "kid", "children", "childrens", "children's",
        "play museum", "play street", "play st", "play center",
        "playground", "indoor play", "family entertainment",
        "trampoline", "arcade", "toddler", "little explorers",
        "discovery center", "imagination", "toy museum",
        "jump", "bounce", "soft play" ,"Play Street Museum"
    ]

    shopping_narrow_keywords = [
        "boutique", "bridal", "women", "womens", "women's",
        "lashes", "nails", "cosmetics", "makeup", "jewelry"
    ]

    shopping_general_keywords = [
        "mall", "market", "shopping center", "outlet", "bookstore",
        "general store", "plaza", "district", "retail"
    ]

    if profile.group_type in ("solo", "couple"):
        if any(word in text_blob for word in [
            "play museum", "play center", "indoor play", "toddler", "kids", "children"
        ]):
            score -= 100

    # place style
    if profile.place_style == "hidden_gems":
        if any(word in text_blob for word in [
            "local", "coffee", "cafe", "market", "garden", "bookstore", "neighborhood"
        ]):
            score += 12
        if any(word in text_blob for word in ["visitor center", "airport", "mall"]):
            score -= 8

    elif profile.place_style == "tourist_spots":
        if any(word in text_blob for word in [
            "museum", "park", "historic", "landmark", "tower", "zoo", "aquarium"
        ]):
            score += 10

    # group type
    if profile.group_type == "family":
        if any(word in text_blob for word in [
            "park", "zoo", "museum", "garden", "family", "aquarium"
        ]):
            score += 12
        if any(word in text_blob for word in kid_keywords):
            score += 14
        if any(word in text_blob for word in ["bar", "nightclub", "lounge"]):
            score -= 20
        if interest == 'shopping' and any(word in text_blob for word in shopping_general_keywords):
            score += 6

    elif profile.group_type == "couple":
        if any(word in text_blob for word in [
            "scenic", "garden", "romantic", "wine", "view", "bistro"
        ]):
            score += 12
        if any(word in text_blob for word in kid_keywords):
            score -= 18
        if interest == 'shopping':
            if any(word in text_blob for word in shopping_general_keywords):
                score += 8

    elif profile.group_type == "friends":
        if any(word in text_blob for word in [
            "bar", "market", "entertainment", "social", "brew", "nightlife"
        ]):
            score += 12
        if interest == 'shopping' and any(word in text_blob for word in shopping_general_keywords):
            score += 8

    elif profile.group_type == "solo":
        child_focused = any(word in text_blob for word in kid_keywords)

        if any(word in text_blob for word in [
            "museum", "coffee", "park", "bookstore", "walk", "historic"
        ]) and not child_focused:
            score += 8

        if child_focused:
            score -= 120

        if interest == "shopping":
            if any(word in text_blob for word in shopping_general_keywords):
                score += 10
            if any(word in text_blob for word in shopping_narrow_keywords):
                score -= 10

    # food focus
    if profile.food_focus and interest in ("food", "coffee"):
        score += 8

    # budget scoring
    if profile.budget == "low":
        if isinstance(price_level, int):
            if price_level <= 1:
                score += 10
            elif price_level >= 3:
                score -= 18

        if any(word in text_blob for word in [
            "cafe", "park", "market", "trail", "historic", "coffee"
        ]):
            score += 8
        if any(word in text_blob for word in [
            "steakhouse", "luxury", "resort", "fine dining"
        ]):
            score -= 12

    elif profile.budget == "medium":
        if isinstance(price_level, int):
            if price_level == 2:
                score += 12
            elif price_level == 1:
                score += 4
            elif price_level == 3:
                score -= 10
            elif price_level >= 4:
                score -= 20

        if any(word in text_blob for word in [
            "fine dining", "luxury", "upscale", "resort"
        ]):
            score -= 10

    elif profile.budget == "high":
        if isinstance(price_level, int):
            if price_level >= 3:
                score += 10
            elif price_level <= 1:
                score -= 4

        if any(word in text_blob for word in [
            "steakhouse", "fine dining", "resort", "upscale", "grill"
        ]):
            score += 10

    return score


def estimate_visit_minutes(place: dict, interest: str | None = None) -> int:
    name = (place.get("name") or "").lower()
    address = (place.get("address") or "").lower()
    text_blob = f"{name} {address}"
    interest = (interest or place.get("_interest") or "").lower()

    if any(word in text_blob for word in ["zoo", "theme park", "aquarium", "water park", "amusement"]):
        return 300  # 5h

    if any(word in text_blob for word in ["museum", "gallery", "science center", "botanical garden"]):
        return 180  # 3h

    if any(word in text_blob for word in ["park", "garden", "historic", "monument", "trail", "nature"]):
        return 120  # 2h

    if any(word in text_blob for word in ["mall", "shopping center", "market", "outlet"]):
        return 150  # 2.5h

    if any(word in text_blob for word in ["restaurant", "bistro", "grill", "steakhouse", "brunch"]):
        return 90  # 1.5h

    if any(word in text_blob for word in ["coffee", "cafe", "espresso", "bakery"]):
        return 60  # 1h

    if any(word in text_blob for word in ["bar", "nightclub", "lounge", "brewery"]):
        return 120  # 2h

    mapping = {
        "coffee": 60,
        "food": 90,
        "museums": 180,
        "parks": 120,
        "history": 120,
        "shopping": 150,
        "nightlife": 120,
        "outdoors": 180,
    }
    return mapping.get(interest, 90)


def is_long_activity(place: dict, interest: str | None = None) -> bool:
    return estimate_visit_minutes(place, interest) >= 180

def get_day_budget_minutes(profile: Optional[TripProfile] = None) -> int:
    profile = profile or TripProfile()

    if profile.pace == "relaxed":
        return 360   # 5h
    elif profile.pace == "packed":
        return 660   # 9h
    return 540       # 7h balanced


def minutes_to_hhmm(total_minutes: int) -> str:
    hours = total_minutes // 60
    mins = total_minutes % 60
    return f"{hours:02d}:{mins:02d}"


def get_day_start_minutes(profile: Optional[TripProfile] = None) -> int:
    profile = profile or TripProfile()

    if profile.pace == "relaxed":
        return 10 * 60
    elif profile.pace == "packed":
        return 8 * 60 + 30
    return 9 * 60

def build_day_time_slots(profile: Optional[TripProfile] = None) -> list[tuple[str, str]]:
    profile = profile or TripProfile()

    if profile.pace == "relaxed":
        return [
            ("10:00", "11:30"),
            ("13:00", "15:00"),
            ("17:00", "19:00"),
        ]
    elif profile.pace in ("fast", "packed"):
        return [
            ("08:30", "09:30"),
            ("10:30", "12:00"),
            ("13:00", "14:30"),
            ("15:30", "17:00"),
            ("18:30", "21:00"),
        ]
    else:
        return [
            ("09:00", "10:30"),
            ("12:00", "13:30"),
            ("15:30", "17:00"),
            ("18:30", "20:30"),
        ]


def get_slot_interest_preferences(profile: Optional[TripProfile], max_stops_per_day: int) -> list[list[str]]:
    profile = profile or TripProfile()

    evening = ["nightlife", "food", "shopping"]
    if profile.group_type == "family":
        evening = ["food", "parks", "museums"]
    elif profile.group_type == "couple":
        evening = ["food", "nightlife", "shopping"]
    elif profile.group_type == "solo":
        evening = ["food", "history", "nightlife"]


    if max_stops_per_day <= 2:
        return [
            ["coffee"],
            ["museums", "parks", "shopping", "history", "food"],
        ]

    if max_stops_per_day >= 4:
        return [
            ["coffee"],
            ["museums", "history", "parks"],
            ["shopping", "parks", "museums"],
            ["food", "shopping", "parks"],
            evening,
        ]

    return [
        ["coffee"],
        ["museums", "history", "parks", "shopping"],
        evening,
    ]


def get_place_open_minute(place: dict, day_index: int) -> int | None:
    weekday_lines = place.get("hours") or []
    if not weekday_lines:
        return None

    line = weekday_lines[day_index % len(weekday_lines)]
    if not line:
        return None

    if "Closed" in line:
        return None
    if "Open 24 hours" in line:
        return 0

    _, raw_ranges = line.split(":", 1)
    raw_ranges = raw_ranges.strip()

    first_range = raw_ranges.split(",")[0].strip()
    parts = re.split(r"\s*[–-]\s*", first_range)
    if len(parts) != 2:
        return None

    return parse_clock_to_minutes(parts[0])


def get_place_open_close_minutes(place: dict, weekday_index: int) -> tuple[int | None, int | None]:
    weekday_lines = place.get("hours") or []
    if not weekday_lines or weekday_index < 0 or weekday_index >= len(weekday_lines):
        return (None, None)

    line = weekday_lines[weekday_index]
    if not line:
        return (None, None)

    if "Closed" in line:
        return (None, None)
    if "Open 24 hours" in line:
        return (0, 24 * 60)

    _, raw_ranges = line.split(":", 1)
    raw_ranges = raw_ranges.strip()

    first_range = raw_ranges.split(",")[0].strip()
    parts = re.split(r"\s*[–-]\s*", first_range)
    if len(parts) != 2:
        return (None, None)

    open_label = parts[0].strip()
    close_label = parts[1].strip()

    open_min = parse_clock_to_minutes(open_label)
    close_min = parse_clock_to_minutes(close_label)

    if open_min is None and close_min is not None:
        close_has_meridiem = bool(re.search(r"(AM|PM)$", re.sub(r"\s+", "", close_label.upper())))
        open_has_meridiem = bool(re.search(r"(AM|PM)$", re.sub(r"\s+", "", open_label.upper())))

        if close_has_meridiem and not open_has_meridiem:
            close_norm = re.sub(r"\s+", "", close_label.upper()).replace(".", "")
            inferred_meridiem = "PM" if close_norm.endswith("PM") else "AM"
            open_min = parse_clock_to_minutes(f"{open_label} {inferred_meridiem}")

    if open_min is None or close_min is None:
        return (None, None)

    if close_min <= open_min:
        close_min += 24 * 60

    return (open_min, close_min)

def build_balanced_itinerary(
    grouped_places: dict[str, List[dict]],
    days: int,
    profile: Optional[TripProfile] = None,
    max_stops_per_day: int = 3,
    start_date:Optional[str] = None,
) -> List[dict]:
    profile = profile or TripProfile()

    day_budget = get_day_budget_minutes(profile)
    day_start = get_day_start_minutes(profile)
    slot_preferences = get_slot_interest_preferences(profile, max_stops_per_day)
    time_slots = build_day_time_slots(profile)

    itinerary = [
        {
            "day": d,
            "stops": [],
            "_used_minutes": 0,
            "_has_long_activity": False,
            "_clock": day_start,
        }
        for d in range(1, days + 1)
    ]

    pools: dict[str, List[dict]] = {
        interest: list(places)
        for interest, places in grouped_places.items()
    }

    used_place_ids: set[str] = set()

    def pop_next_from_interest(interest: str) -> Optional[dict]:
        pool = pools.get(interest, [])
        while pool:
            place = pool.pop(0)
            pid = place.get("place_id")
            if pid and pid not in used_place_ids:
                used_place_ids.add(pid)
                return place
        return None

    def pop_next_any(exclude_interests: set[str]) -> Optional[dict]:
        ranked_candidates = []
        for interest, pool in pools.items():
            if interest in exclude_interests:
                continue
            while pool and pool[0].get("place_id") in used_place_ids:
                pool.pop(0)
            if pool:
                ranked_candidates.append((pool[0].get("_score", 0), interest))

        if not ranked_candidates:
            for interest, pool in pools.items():
                while pool and pool[0].get("place_id") in used_place_ids:
                    pool.pop(0)
                if pool:
                    ranked_candidates.append((pool[0].get("_score", 0), interest))

        if not ranked_candidates:
            return None

        ranked_candidates.sort(reverse=True)
        _, best_interest = ranked_candidates[0]
        return pop_next_from_interest(best_interest)

    def can_fit(day_info: dict, place: dict) -> bool:
        duration = estimate_visit_minutes(place)
        effective_duration = min(duration,90)
        long_flag = is_long_activity(place)

        if day_info["_used_minutes"] + effective_duration > day_budget:
            return False

        if long_flag and day_info["_has_long_activity"]:
            return False

        return True

    for day_index in range(days):
        used_interests_today: set[str] = set()
        weekday_index = get_real_weekday_index(start_date, day_index)

        for slot_index in range(max_stops_per_day):
            preferred_interests = slot_preferences[min(slot_index, len(slot_preferences) - 1)]
            chosen = None

            attempts = 0
            max_attempts = 12

            while attempts < max_attempts and not chosen:
                attempts += 1
                candidate = None

                for interest in preferred_interests:
                    if interest in used_interests_today:
                        continue

                    possible = pop_next_from_interest(interest)
                    if not possible:
                        continue

                    possible["_interest"] = possible.get("_interest") or interest

                    if can_fit(itinerary[day_index], possible):
                        candidate = possible
                        break
                    else:
                        pid = possible.get("place_id")
                        if pid:
                            used_place_ids.discard(pid)
                        pools.setdefault(interest, []).append(possible)

                if not candidate:
                    fallback = pop_next_any(used_interests_today)
                    if fallback and can_fit(itinerary[day_index], fallback):
                        candidate = fallback
                    elif fallback:
                        pid = fallback.get("place_id")
                        if pid:
                            used_place_ids.discard(pid)
                        pools.setdefault(fallback.get("_interest", "other"), []).append(fallback)

                if not candidate:
                    break

                duration = estimate_visit_minutes(candidate)

                slot_start_hhmm, slot_end_hhmm = time_slots[min(slot_index, len(time_slots) - 1)]
                slot_start_min = hhmm_to_minutes(slot_start_hhmm)

                start_min = max(itinerary[day_index]["_clock"], slot_start_min)


                open_min, close_min = get_place_open_close_minutes(candidate, weekday_index)

                if open_min is None and close_min is None:
                    print("REJECTED HOURS:", candidate.get("name"), candidate.get("hours"))
                    pid = candidate.get("place_id")
                    if pid:
                        used_place_ids.discard(pid)
                    pools.setdefault(candidate.get("_interest", "other"), []).append(candidate)
                    continue

                if open_min is not None and start_min < open_min:
                    start_min = open_min

                end_min = start_min + duration

                if close_min is not None and end_min > close_min:
                    adjusted_duration = close_min - start_min

                    minimum_duration_by_interest = {
                        "coffee": 30,
                        "food": 45,
                        "museums": 60,
                        "parks": 45,
                        "history": 45,
                        "shopping": 60,
                        "nightlife": 45,
                        "outdoors": 60,
                    }

                    min_allowed = minimum_duration_by_interest.get(
                        candidate.get("_interest", "other"),
                        45
                    )

                    if adjusted_duration < min_allowed:
                        pid = candidate.get("place_id")
                        if pid:
                            used_place_ids.discard(pid)
                        pools.setdefault(candidate.get("_interest", "other"), []).append(candidate)
                        continue

                    end_min = close_min

                if end_min - day_start > day_budget:
                    pid = candidate.get('place_id')
                    if pid:
                        used_place_ids.discard(pid)
                    pools.setdefault(candidate.get('_interest', 'other'), []).append(candidate)
                    continue
    
                chosen = candidate
                chosen["_scheduled_start_min"] = start_min
                chosen["_scheduled_end_min"] = end_min
                used_interests_today.add(chosen.get("_interest", "other"))

            if not chosen:
                continue

            duration = estimate_visit_minutes(chosen)
            start_min = chosen.get("_scheduled_start_min", itinerary[day_index]["_clock"])
            end_min = chosen.get("_scheduled_end_min", start_min + duration)
            arrival_hhmm = minutes_to_hhmm(start_min)
            departure_hhmm = minutes_to_hhmm(end_min)

            itinerary[day_index]["stops"].append({
                "place_id": chosen.get("place_id"),
                "name": chosen.get("name"),
                "category": chosen.get("_interest"),
                "address": chosen.get("address") or "",
                "rating": chosen.get("rating"),
                "lat": chosen.get("lat"),
                "lng": chosen.get("lng"),
                "arrival_time": arrival_hhmm,
                "departure_time": departure_hhmm,
                "suggestion_note": (
                    f"Suggested from {chosen.get('_interest', 'mixed')} results. "
                    f"Estimated visit time: {duration} min."
                ),
            })

            actual_duration = end_min - start_min
            travel_buffer = 20
            itinerary[day_index]["_used_minutes"] += actual_duration + travel_buffer
            itinerary[day_index]["_clock"] = end_min + travel_buffer

            if is_long_activity(chosen):
                itinerary[day_index]["_has_long_activity"] = True

    for day in itinerary:
        day.pop("_used_minutes", None)
        day.pop("_has_long_activity", None)
        day.pop("_clock", None)

    return itinerary



def distribute_places_across_days(
    places: List[dict], 
    days: int, 
    profile: Optional[TripProfile] = None,
    max_stops_per_day: int = 3) -> List[dict]:
    itinerary = [{"day": d, "stops": []} for d in range(1, days + 1)]
    time_slots = build_day_time_slots(profile)

    limited = places[: days * max_stops_per_day]

    for idx, place in enumerate(limited):
        day_index = idx % days
        stop_index_for_day = len(itinerary[day_index]["stops"])
        
        arrival_time = None
        departure_time = None
        if stop_index_for_day < len(time_slots):
            arrival_time, departure_time = time_slots[stop_index_for_day]

        itinerary[day_index]["stops"].append({
            "place_id": place.get("place_id"),
            "name": place.get("name"),
            "category": place.get("_interest"),
            "address": place.get("address") or "",
            "rating": place.get("rating"),
            "lat": place.get("lat"),
            "lng":place.get("lng"),
            "arrival_time": arrival_time,
            "departure_time": departure_time,
            "suggestion_note": "Suggested by AI. You can keep, replace, or edit this stop.",
        })
    return itinerary


async def fetch_place_details_for_scoring(place_id: str) -> dict:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return {}

    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "key": api_key,
        "fields": ",".join([
            "place_id",
            "opening_hours",
            "price_level",
            "types",
            "name",
            "formatted_address",
        ]),
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()

        if data.get("status") != "OK":
            return {}

        result = data.get("result", {}) or {}
        opening = result.get("opening_hours") or {}

        return {
            "open_now": opening.get("open_now"),
            "hours": opening.get("weekday_text", []),
            "price_level": result.get("price_level"),
            "types": result.get("types", []),
        }
    except Exception:
        return {}

def parse_google_duration_to_minutes(duration: str | None) -> int | None:
    """
    This will convert google routes api duration text into minutes.
    google normally returns duration like 735s
    """
    if not duration:
        return None
    if not duration.endswith("s"):
        return None

    try:
        seconds = float(duration.replace("s", ""))
    except ValueError:
        return None

    minutes = int((seconds + 59) // 60)

    return minutes

async def fetch_google_drive_route(
    origin_lat: float,
    origin_lng: float,
    destination_lat: float,
    destination_lng: float,
) -> dict:

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_MAPS_API_KEY is not set"
        )

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.distanceMeters,routes.duration",
    }

    payload = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": origin_lat,
                    "longitude": origin_lng,
                }
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": destination_lat,
                    "longitude": destination_lng,
                }
            }
        },
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Google Routes API request failed",
                "google_status_code": response.status_code,
                "google_response": response.text,
            },
        )

    data = response.json()
    routes = data.get("routes", [])

    if not routes: 
        raise HTTPException(
            status_code=502,
            detail="Google Routes API did not return a route.",
        )

    route = routes[0]

    distance_meters = route.get("distanceMeters")
    duration_text = route.get("duration")

    duration_minutes = parse_google_duration_to_minutes(duration_text)

    distance_miles = None
    if isinstance(distance_meters, (int, float)):
        distance_miles = round(distance_meters / 1609.344, 2)
    
    return {
        "distance_miles": distance_miles,
        "distance_meters": distance_meters,
        "duration_minutes": duration_minutes,
        "duration_text": duration_text,
    }

@app.post("/ai/itinerary", response_model=AIItineraryResponse)
async def ai_itinerary(body: ItineraryRequest):
    started = time.perf_counter()

    profile = body.profile or TripProfile()

    default_interests_by_group = {
        "solo": ["coffee", "museums", "parks", "history", "shopping", "food"],
        "couple": ["coffee", "museums", "shopping", "food", "nightlife", "parks"],
        "friends": ["coffee", "shopping", "parks", "food", "nightlife", "museums"],
        "family": ["parks", "museums", "shopping", "food", "history"],
    }

    interests = body.interests or default_interests_by_group.get(
        profile.group_type,
        ["coffee", "museums", "parks", "shopping", "food"]
    )
    
    print("AI itinerary start:", body.destination, "days=", body.days, "interests=", interests)


    grouped_places: dict[str, List[dict]] = {}

    for interest in interests:
        interest_started = time.perf_counter()

        results = await search_places_for_interests(body.destination, interest, profile)
        results = results[:5]

        scored = []
        
        detail_tasks = [
            fetch_place_details_for_scoring(place.get('place_id'))
            for place in results
        ]
        detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)
        
        for place, details in zip(results, detail_results):
            if isinstance(details, dict) and details:
                place.update(details)
            place["_interest"] = interest
            place["_score"] = score_place(place,interest,profile)
            scored.append(place)

        seen = set()
        ranked = []
        for place in sorted(scored, key=lambda p: p["_score"], reverse=True):
            pid = place.get("place_id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            ranked.append(place)

        grouped_places[interest] = ranked
        print(f"{interest} finished in {time.perf_counter() - interest_started:.2f}s")

    max_stops_per_day = 4
    if profile.pace == "relaxed":
        max_stops_per_day = 3
    elif profile.pace == "packed":
        max_stops_per_day = 5

    itinerary = build_balanced_itinerary(
        grouped_places=grouped_places,
        days=body.days,
        profile=profile,
        max_stops_per_day=max_stops_per_day,
        start_date = body.start_date,
    )

    print("AI itinerary total:", round(time.perf_counter() - started, 2), "seconds")


    return {
        "destination": body.destination,
        "days": body.days,
        "itinerary": itinerary,
    }



def hhmm_to_minutes(hhmm:str) -> int:
    h,m = hhmm.split(":")
    return int(h) * 60 + int(m)

def parse_clock_to_minutes(label: str) -> int | None:
    if not label:
        return None

    s = str(label).upper().strip()

    s = re.sub(r"\s+", "", s)

    s = s.replace(".", "")

    m = re.match(r"^(\d{1,2}):(\d{2})(AM|PM)$", s)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2))
    meridiem = m.group(3)

    if hour == 12:
        hour = 0
    if meridiem == "PM":
        hour += 12

    return hour * 60 + minute


def is_place_open_for_time(place: dict, day_index: int, arrival_hhmm: str, departure_hhmm: str | None = None) -> bool:
    weekday_lines = place.get("hours") or []
    if not weekday_lines:
        return True 

    line = weekday_lines[day_index % len(weekday_lines)] if weekday_lines else None
    if not line:
        return True

    if "Closed" in line:
        return False

    if "Open 24 hours" in line:
        return True

    _, raw_ranges = line.split(":", 1)
    raw_ranges = raw_ranges.strip()

    arrival_min = hhmm_to_minutes(arrival_hhmm)
    departure_min = hhmm_to_minutes(departure_hhmm) if departure_hhmm else arrival_min

    ranges = [r.strip() for r in raw_ranges.split(",") if r.strip()]
    for r in ranges:
        parts = re.split(r"\s*[–-]\s*", r)
        if len(parts) != 2:
            continue

        start_min = parse_clock_to_minutes(parts[0])
        end_min = parse_clock_to_minutes(parts[1])
        if start_min is None or end_min is None:
            continue

        # handle overnight close like 10:00 PM - 2:00 AM
        if end_min <= start_min:
            if arrival_min >= start_min or departure_min <= end_min:
                return True
        else:
            if arrival_min >= start_min and departure_min <= end_min:
                return True

    return False
        

"""
#AI assistant
@app.post("/ai/itinerary")
async def ai_itinerary(body: ItineraryRequest):
    itinerary = []
    for d in range(1, body.days + 1):
        itinerary.append({
            "day": d,
            "theme": " / ".join(body.interests) if body.interests else "General",
            "plan": [
                {"time": "09:00", "activity": f"Explore top sights in {body.destination}"},
                {"time": "13:00", "activity": "Lunch at a popular spot"},
                {"time": "15:00", "activity": "Something aligned with interests"},
                {"time": "19:00", "activity": "Dinner + evening walk"},
            ],
        })
    return {"destination": body.destination, "days": body.days, "itinerary": itinerary, "note": "AI stub"}
'''
"""
