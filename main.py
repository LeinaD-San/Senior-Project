from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets

from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse
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
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent

load_dotenv()

openai_client = OpenAI()

app = FastAPI(title="Travel Agent API")


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
            
            #temporarily commenting these out until the database issue is fixed where user is not being read
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR"))
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


class TripUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


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

class TripProfile(BaseModel):
    group_type: str = 'solo'
    pace: str = 'balanced'
    budget: str = 'medium'
    place_style: str = 'mix'
    food_focus: bool = True

class ItineraryRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=120)
    days: int = Field(ge=1, le=14)
    interests: List[str] = []
    profile: Optional[TripProfile]=None


#AI classes will give the backend a clean response format
class AIStop(BaseModel):
    place_id: str
    name: str
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


def _new_salt_b64() -> str:
    return base64.b64encode(secrets.token_bytes(16)).decode("utf-8")


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
    trip = models.Trip(user_id=user.id, title=payload.title, destination=payload.destination)
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return {"id": trip.id, "title": trip.title, "destination": trip.destination}


@app.get("/trips")
def list_trips(db: db_dependency, user: models.User = Depends(get_current_user)):
    trips = db.query(models.Trip).filter(models.Trip.user_id == user.id).all()
    return [
        {'id': t.id, 'title': t.title, 'destination': t.destination}
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
    db.commit()
    db.refresh(trip)
    return {"id": trip.id, "title": trip.title, "destination": trip.destination}


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

    #we will use position=next_pos when creating the item. 

    item = models.TripItem(
        trip_id=trip_id,
        day=payload.day,
        position=next_pos,
        place_id=payload.place_id,
        name=payload.name,
        notes=payload.notes,
        lat= payload.lat,
        lng=payload.lng,
        address =payload.address,
        rating=payload.rating,
        arrival_time=payload.arrival_time,
        departure_time=payload.departure_time,
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
        "items": [
            {
                "id": i.id,
                "day": i.day,
                "position": i.position,
                "place_id": i.place_id,
                "name": i.name,
                "notes": i.notes,
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
    if 'completed' in updates:
        item.completed = 1 if updates['completed'] else 0
    if 'arrival_time' in updates:
        item.arrival_time = updates['arrival_time']
    if 'departure_time' in updates:
        item.departure_time = updates['departure_time']
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
            {"id": i.id, "position": i.position, "place_id": i.place_id, "name": i.name, "notes": i.notes}
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
    return FileResponse("account.html", media_type="text/html")   


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
            "lat": location.get("lat"),
            "lng": location.get("lng"),
            "photo_url": photo_urls[0] if raw_photos else None,
            "photos": photo_urls,
        })

    return {"query": q, "count": len(results), "results": results}


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
    "shopping": "shopping",
    "outdoors": "outdoor attractions",
    "history": "historic sites",
}

def build_interest_query(destination: str, interest: str, profile: Optional[TripProfile]) -> str:
    search_term = INTEREST_QUERY_MAP.get(interest, interest)
    profile = profile or TripProfile()

    modifiers: list[str] = []

    if profile.budget == 'low':
        modifiers.append('affordable')
    elif profile.budget == 'high':
        modifiers.append('upscale')

    if profile.place_style == 'hidden_gems':
        modifiers.append('local hidden gems')
    elif profile.place_style == 'tourist_spots':
        modifiers.append('popular tourist spots')

    if profile.group_type == 'family':
        modifiers.append('family friendly')
    elif profile.group_type == 'couple':
        modifiers.append('romantic scenic')
    elif profile.group_type == 'friends':
        modifiers.append('fun social')
    elif profile.group_type == 'solo':
        modifiers.append('solo friendly')

    if profile.food_focus and interest in ('food', 'coffee'):
        modifiers.append('popular local')

    modifier_text = ' '.join(m for m in modifiers if m).strip()
    if modifier_text:
        return f'{modifier_text} {search_term} in {destination}'
    return f'{search_term} in {destination}'

#will give us real place candidates from google. 
async def search_places_for_interests(destination: str, interest:str, profile: Optional[TripProfile]=None) -> List[dict]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is not set")

    query = build_interest_query(destination, interest, profile)

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
    for p in data.get("results", [])[:8]:
        location = p.get("geometry",{}).get("location", {})
        results.append({
            "place_id": p.get("place_id"),
            "name": p.get("name"),
            "address": p.get("formatted_address"),
            "rating": p.get("rating"),
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


def score_place(place: dict, interest:str, profile: Optional[TripProfile]) -> float:
    profile = profile or TripProfile()
    score = 0.0

    rating = place.get('rating')
    if isinstance(rating, (int, float)):
        score += float(rating) * 10

    name = (place.get('name') or '').lower()
    address = (place.get('address') or '').lower()
    text_blob = f'{name} {address}'

    if profile.place_style == 'hidden_gems':
        if 'museum of' not in text_blob and 'visitor center' not in text_blob:
            score += 8
    elif profile.place_style == 'tourist_spots':
        if 'museum' in text_blob or 'park' in text_blob or 'historic' in text_blob:
            score += 6
    if interest in ("food", "coffee") and profile.food_focus:
        score += 5
    
    if profile.group_type == "family" and ("park" in text_blob or "museum" in text_blob):
        score += 4
    if profile.group_type == "couple" and ("cafe" in text_blob or "scenic" in text_blob):
        score += 5
    if profile.group_type == "friends" and ("bar" in text_blob or "shopping" in text_blob):
        score += 4
    
    return score

def build_day_time_slots(profile: Optional[TripProfile] = None) -> list[tuple[str, str]]:
    profile = profile or TripProfile()

    if profile.pace == "relaxed":
        return [
            ("10:00", "11:30"),
            ("13:00", "14:30"),
            ("16:00", "18:00"),
        ]
    elif profile.pace == "fast":
        return [
            ("08:30", "10:00"),
            ("10:30", "12:00"),
            ("13:00", "14:30"),
        ]
    else:
        return [
            ("09:00", "10:30"),
            ("12:00", "13:30"),
            ("15:00", "17:00"),
        ]

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
            "address": place.get("address") or "",
            "rating": place.get("rating"),
            "lat": place.get("lat"),
            "lng":place.get("lng"),
            "arrival_time": arrival_time,
            "departure_time": departure_time,
            "suggestion_note": "Suggested by AI. You can keep, replace, or edit this stop.",
        })
    return itinerary


@app.post("/ai/itinerary", response_model=AIItineraryResponse)
async def ai_itinerary(body: ItineraryRequest):
    interests = body.interests or ["food", "coffee", "parks"]

    all_places = []
    for interest in interests:
        results = await search_places_for_interests(body.destination, interest)
        for place in results: 
            place["_interest"] = interest
        all_places.extend(results)
    
    deduped = dedupe_places(all_places)

    for place in deduped:
        place ["_score"] = score_place(place, place.get("_interest", ""), body.profile)

    #sort better rated places first when possible
    deduped.sort(key=lambda p: (p.get("rating") is not None, p.get("rating") or 0), reverse=True)

    itinerary = distribute_places_across_days(deduped, body.days, max_stops_per_day=3)
    
    return {
        "destination": body.destination,
        "days": body.days,
        "itinerary": itinerary,
    }

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