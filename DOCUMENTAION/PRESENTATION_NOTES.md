# trAgent — Project Overview (Presentation Notes)

## What is trAgent?

trAgent is a web app for local discovery + trip planning.

- Users search for a destination (city/neighborhood)
- Pick interests (food, coffee, parks, etc.)
- See results, select stops, and build a day-by-day itinerary
- Save itineraries to an account and reopen/edit them later

## The Problem

Planning a day out (or a multi-day trip) usually requires jumping between multiple apps:
- Search engines, maps, review sites
- Notes apps for tracking places
- Manual copy/paste of addresses and links

trAgent’s goal is to reduce friction: search, select, organize, and save in one place.

## Demo Flow (Recommended)

- Home (`/`): start a trip by entering destination
- Plan screen: choose destination + number of days + interests
- Results: choose which places you want
- Planner/Itinerary notepad (`/planner`): add/remove/reorder stops, mark completed, add notes
- Save trip: requires login → creates a saved itinerary
- “My Saved Trips”: reopen or delete previous itineraries

## Key Features

**Discovery**
- Search places using Google Places (Text Search)
- Optional nearby search support

**Itinerary building**
- Multi-day structure (Day 1..N)
- Add places to specific days
- Reorder places within a day
- Remove places

**Itinerary tracking**
- Notes per stop
- Completed checkbox per stop

**Accounts + persistence**
- Create account / login
- Saved trips tied to a user
- Reopen saved trips and continue editing

## Tech Stack

**Backend**
- FastAPI (`main.py`)
- SQLAlchemy models (`models.py`)
- Postgres (Docker via `docker-compose.yml`)

**Frontend**
- Plain HTML/CSS/JS (served by FastAPI)
- Key screens:
  - `itinerary_page.html` (home + plan + results flow)
  - `planner.html` (saved trips + itinerary notepad)
  - `login.html` (login/register)

## System Architecture (High-level)

- Browser UI pages call FastAPI endpoints
- FastAPI proxies requests to Google Places
- FastAPI stores user/trip data in Postgres

**External dependency**
- Google Maps/Places API

## Data Model (Database)

Tables (SQLAlchemy in `models.py`):
- `users`: account email + password hash/salt
- `session_tokens`: bearer tokens for login sessions
- `trips`: saved itinerary header (title, destination, user_id)
- `trip_item`: individual stops (day, position, place_id, name, notes, completed, optional lat/lng/address/rating)

## Important API Endpoints

**Auth**
- `POST /auth/register` → returns `{token}`
- `POST /auth/login` → returns `{token}`
- `POST /auth/logout`
- `GET /me`

**Trips** (require `Authorization: Bearer <token>`)
- `POST /trips`
- `GET /trips`
- `GET /trips/{trip_id}`
- `DELETE /trips/{trip_id}`
- `POST /trips/{trip_id}/items`
- `PATCH /trips/{trip_id}/items/{item_id}` (notes/completed)
- `DELETE /trips/{trip_id}/items/{item_id}`
- `PUT /trips/{trip_id}/days/{day}/reorder`

**Places (Google proxy)**
- `GET /places/search?q=...`
- `GET /places/nearby?lat=...&lng=...`
- `GET /places/{place_id}` (details + photo URLs)

## Security Notes (What to Mention)

- API keys are loaded from environment variables (`.env`), not committed
- Passwords are not stored in plaintext:
  - per-user salt + PBKDF2 hash
- API uses bearer session tokens (stored in browser localStorage for demo)

## Setup / Run Notes (Common Gotchas)

- Start Postgres via Docker
- If port `5432` is in use locally, the compose file uses host port `5433`
- After schema changes (auth tables), a clean DB volume may be needed:
  - `docker compose down -v` then `docker compose up -d`

## Challenges / Lessons Learned

- Managing user flow between pages (home → plan → results → planner)
- Handling auth state consistently across pages
- Keeping the demo reliable even when external APIs fail

## Future Improvements

- Better UI for saved trips (rename trip, edit destination)
- Place photos in results consistently + caching
- Better error messages and loading states
- Automated tests (API + UI)
- Replace localStorage tokens with httpOnly cookies
