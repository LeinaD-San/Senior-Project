# trAgent By : Alan Cuellar, Daniel Sanchez, Nick De Leon, Troy Rodriguez

trAgent is a web app that helps people discover new local spots (food, coffee, parks, events) and quickly plan a day-by-day itinerary. Users can search for places, generate an itinerary based on destination and interests, save trips with multiple stops, and edit notes to build a shareable plan.

## Local Run

### 1) Environment variables

- Copy `.env.example` to `.env` and fill in `GOOGLE_MAPS_API_KEY`.
- If you want the live map on the landing page, also set `GOOGLE_MAPS_JS_API_KEY`.

### 2) Install deps

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Start the API + landing page

```bash
source .venv/bin/activate
uvicorn main:app --reload
```

- Landing page: `http://127.0.0.1:8000/`
- Itinerary page: `http://127.0.0.1:8000/itinerary`
- API docs: `http://127.0.0.1:8000/docs`

## Project Stages (Detailed Pace Plan)

### Stage 1 — Get It Running (1–2 days)
- Goal: Any teammate can clone the repo and run it.
- Tasks:
  - Decide the standard local run setup (Docker Postgres + local FastAPI)
  - Add `.env.example` with required values (`DATABASE_URL`, `GOOGLE_MAPS_API_KEY`)
  - Document the run commands in this README (`docker-compose up -d`, install deps, run server)
  - Verify the API is reachable at `/docs` and `/health`
- Done when:
  - A fresh machine can run it in under 15 minutes
  - No keys or secrets are committed

### Stage 2 — Trip Builder (3–5 days)
- Goal: Users can create trips and manage stops reliably.
- Tasks:
  - Add missing API endpoints (as needed): list trips, delete trip, delete stop, update stop notes
  - Make response shapes consistent (so the frontend can rely on them)
  - Ensure DB relationships behave correctly (trip has many items; deleting a trip cleans up items if desired)
- Done when:
  - You can create a trip, add 5 stops, edit notes, remove a stop, and reload to see it persisted

### Stage 3 — Place Finder (3–5 days)
- Goal: Users can find places and add them to a trip.
- Tasks:
  - Improve `/places/search` to support:
    - destination-only search (example: “cafes in Brownsville”)
    - optional `lat/lng/radius` nearby search
    - basic filters (example: min rating) if supported
  - Normalize results (place_id, name, address, rating)
  - Add “Add to Trip” flow that stores `place_id` + `name` + `notes`
- Done when:
  - Searching for “bookstore Brownsville” returns usable results and can be saved into a trip

### Stage 4 — Auto Itinerary (4–7 days)
- Goal: Generate a simple, real itinerary and save it.
- Tasks:
  - Define itinerary output format (days → time blocks → selected places)
  - Implement generation logic:
    - map interests to search queries/categories (coffee, parks, museums, food)
    - fetch candidate places from Google Places
    - select a reasonable number of stops per day (example: 3–5)
  - Save generated stops into `TripItem` automatically
- Done when:
  - “Generate itinerary” returns real places and the trip view shows those items saved

### Stage 5 — Web Pages (4–7 days)
- Goal: The product looks and feels like the landing page concept (`nearby-landing.html`).
- Tasks:
  - Build frontend screens:
    - Landing page
    - Plan form (destination, days, interests)
    - Results/itinerary view (day tabs/cards)
    - Saved trip view (edit notes, remove stop)
  - Connect to the API and add loading/error states
  - Basic responsive layout (works on phone and desktop)
- Done when:
  - A non-technical user can go landing → generate → save → reopen trip

### Stage 6 — Final Polish (3–7 days)
- Goal: Stable, demo-ready, and clearly focused on local discovery.
- Tasks:
  - Add “prefer local” logic (simple heuristics to down-rank obvious chains)
  - Improve error messages (missing API key, no results, DB down)
  - Add basic tests (at least trips + itinerary endpoint)
  - Write a demo script (exact steps and sample queries)
- Done when:
  - You can demo it multiple times in a row without troubleshooting
  - EVERYTHING WORKS!!!


### SUBJECT TO CHANGE
