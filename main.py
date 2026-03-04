from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Annotated, Optional
import os
import httpx
import models
from database import engine, SessionLocal
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Travel Agent API")

#so frontend can call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],#temp, replace later with frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# creates tables
@app.on_event("startup")
def on_startup():
    models.Base.metadata.create_all(bind=engine)

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

class TripItemCreate(BaseModel):
    day: int = Field(ge=1, le=30)
    place_id: str
    name: str
    notes: str = ""

    lat: Optional[float] = None
    lng: Optional[float] = None
    address: Optional[str] = None
    rating: Optional[float] = None

class ItineraryRequest(BaseModel):
    destination: str
    days: int = Field(ge=1, le=14)
    interests: List[str] = []

#app Health/activity
@app.get("/health")
def health():
    return {"status": "ok"}

#DB--Trips
@app.post("/trips")
def create_trip(payload: TripCreate, db: db_dependency):
    trip = models.Trip(title=payload.title, destination=payload.destination)
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return {"id": trip.id, "title": trip.title, "destination": trip.destination}


@app.get("/trips")
def list_trips(db: db_dependency):
    trips = db.query(models.Trip).all()
    return [
        {'id': t.id, 'title': t.title, 'destination': t.destination}
        for t in trips
    ]


@app.post("/trips/{trip_id}/items")
def add_trip_item(trip_id: int, payload: TripItemCreate, db: db_dependency):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    item = models.TripItem(
        trip_id=trip_id,
        day=payload.day,
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
    return {"id": item.id, "trip_id": item.trip_id, "day": item.day, "place_id": item.place_id, "name": item.name}


@app.get("/trips/{trip_id}")
def get_trip(trip_id: int, db: db_dependency):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    items = db.query(models.TripItem).filter(models.TripItem.trip_id == trip_id).all()
    return {
        "id": trip.id,
        "title": trip.title,
        "destination": trip.destination,
        "items": [
            {"id": i.id, "day": i.day, "place_id": i.place_id, "name": i.name, "notes": i.notes}
            for i in items
        ],
    }

@app.delete('/trips/{trip_id}')
def delete_trip(trip_id: int, db: db_dependency):
    trip = db.get(models.Trip, trip_id)
    if not trip:
        raise HTTPException(status_code=404, detail = 'Trip not found')
    db.delete(trip)
    db.commit()
    return {'status': 'deleted', 'trip_id':trip_id}

@app.delete('/trips/{trip_id}/items/{item_id}')
def delete_trip_item(trip_id: int, item_id: int, db: db_dependency):
    item = db.get(models.TripItem, item_id)

    if not item or item.trip_id != trip_id:
        raise HTTPException(status_code=404, detail='Item not found')
    
    db.delete(item)
    db.commit()
    return{'status': 'deleted', 'item_id':item_id}

#Google Maps
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

@app.get('/places/{places_id}')
async def place_details(place_id:str):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")

    if not api_key:
        raise HTTPException(status_code=500, detail='GOOGLE_MAPS_API_KEY not set')

    url = 'https://maps.googleapis.com/maps/api/place/details/json'

    params = {
        'place_id':place_id,
        'key': api_key
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

    for p in place.get('photos',[]):
        ref = p.get('photo_reference')
        if ref:
            photos.append(
                f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photo_reference={ref}&key={api_key}"
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
        "photos": photos
    }

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