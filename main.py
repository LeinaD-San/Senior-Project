from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Annotated, Optional
import os
import httpx

import models
from database import engine, SessionLocal
from sqlalchemy.orm import Session

app = FastAPI(title="Travel Agent API")

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
        results.append({
            "place_id": p.get("place_id"),
            "name": p.get("name"),
            "address": p.get("formatted_address"),
            "rating": p.get("rating"),
        })

    return {"query": q, "count": len(results), "results": results}

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