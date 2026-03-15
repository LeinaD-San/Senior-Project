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

from pathlib import Path
from fastapi.responses import FileResponse

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


class AuthPayload(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class SessionResponse(BaseModel):
    token: str

class TripItemCreate(BaseModel):
    day: int = Field(ge=1, le=30)
    place_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=1000)

    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    rating: Optional[float] = None


class TripItemUpdate(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=1000)
    completed: Optional[bool] = None

class ItineraryRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=120)
    days: int = Field(ge=1, le=14)
    interests: List[str] = []

class ReorderPayload(BaseModel):
    ordered_item_ids: List[int] = Field(min_length=1)

#app Health/activity
@app.get("/health")
def health():
    return {"status": "ok"}


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
def auth_register(payload: AuthPayload, db: db_dependency):
    existing = db.query(models.User).filter(models.User.email == payload.email.lower()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    salt_b64 = _new_salt_b64()
    password_hash = _hash_password(payload.password, salt_b64)
    user = models.User(email=payload.email.lower(), password_salt=salt_b64, password_hash=password_hash)
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

    return {"token": token}


@app.post("/auth/login", response_model=SessionResponse)
def auth_login(payload: AuthPayload, db: db_dependency):
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
    return {"token": token}


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
    return {"id": user.id, "email": user.email}

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
    input: str = Query(min_lenth = 1, max_length=120),
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
        status_code = 502,
        detail={"google_status": status, 'error': data.get('error_message')},
        
    predictions = []
    for p in data.get('predictions',[]):
        predictions.append({
            'description': p.get('destination'),
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

#-------------------------------------------------------------------
#-------------------------------------------------------------------
#temp helper func.
def generate_ai_outline(destination: str, days: int, interests: List[str]):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")

    interests_text = ", ".join(interests) if interests else "general travel"

    prompt = f"""
You are helping generate a simple travel itinerary outline.

Destination: {destination}
Days: {days}
Interests: {interests_text}

Return valid JSON only with this shape:
{{
  "destination": "string",
  "days": [
    {{
      "day": 1,
      "theme": "short theme",
      "queries": ["query 1", "query 2", "query 3"]
    }}
  ]
}}

Rules:
- Return exactly {days} day objects
- Each day must include 3 search queries
- Queries must be specific Google Places style searches
- Queries must include the destination name
- Keep themes short
- No markdown
- No explanation outside JSON
"""

    response = openai_client.responses.create(
        model="gpt-5-mini",
        input=prompt
    )

    text = response.output_text
    return json.loads(text)


#helper search to return places
async def search_places_query(query: str) -> list[dict]:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail='GOOGLE_MAPS_API_KEY is not set')
    url = 'https://maps.googleapis.com/maps/api/place/textsearch/json'
    params={'query': query, 'key':api_key}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    status = data.get('status')
    if status not in ("OK", 'ZERO_RESULTS'):
        raise HTTPException(
            status_code=502, detail={'googe_status':status, 'error': data.get('error_message')},
        )
    
    results = []
    for p in data.get('results', []):
        location = p.get('geometry', {}).get ('location', {})
        results.append({
            'place_id':p.get('place_id'),
            'name':p.get('name'),
            'address':p.get('formatted_address'),
            'rating':p.get('rating'),
            'lat':location.get('lat'),
            'lng':location.get('lng'),
        })
    return results

#
def dedupe_places(places: list[dict]) -> list[dict]:
    seen = set()
    unique = []

    for place in places:
        place_id = place.get('place_id')
        if not place_id or place_id in seen:
            continue
        seen.add(place_id)
        unique.append(place)
    return unique



#temp replacement for /ai/ititnerary
@app.post("/ai/itinerary")
async def ai_itinerary(body: ItineraryRequest):
    try:
        outline = generate_ai_outline(
            destination=body.destination,
            days=body.days,
            interests=body.interests,
        )

        itinerary_days = []

        for day_info in outline.get("days", []):
            queries = day_info.get("queries", [])
            all_places = []

            for query in queries:
                places = await search_places_query(query)
                all_places.extend(places[:4])

            unique_places = dedupe_places(all_places)[:5]

            itinerary_days.append({
                "day": day_info.get("day"),
                "theme": day_info.get("theme"),
                "queries": queries,
                "places": unique_places,
            })

        return {
            "destination": body.destination,
            "days": body.days,
            "interests": body.interests,
            "itinerary": itinerary_days,
            "note": "AI itinerary with real Google Places results",
        }

    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI returned invalid JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






'''
#temp. replacement for /ai/itinerary, below is the ORIGINAL DO NOT DELETE
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
