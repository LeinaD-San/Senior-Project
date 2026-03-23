# trAgent — Runbook

## Prereqs

- Docker Desktop (for Postgres)
- Python 3

## 1) Configure environment

From the repo root:

```bash
cp .env.example .env
```

Set at least:

- `GOOGLE_MAPS_API_KEY` (required for Places endpoints)
- `GOOGLE_MAPS_JS_API_KEY` (required for the live map UI; if omitted it falls back to `GOOGLE_MAPS_API_KEY`)
- `OPENAI_API_KEY` (required for `/ai/*` endpoints)

## 2) Start Postgres

```bash
docker compose up -d
```

If you get a port conflict on `5432`, either stop your local Postgres or change the host port mapping in `docker-compose.yml` and update `DATABASE_URL` in `.env`.

## 3) Create and activate a virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4) Install dependencies

```bash
pip install -r requirements.txt
```

## 5) Run the server

```bash
uvicorn main:app --reload
```

## 6) Open the app

- Landing page: `http://127.0.0.1:8000/`
- Itinerary page: `http://127.0.0.1:8000/itinerary`
- API docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## Useful commands

- Stop services:
  ```bash
  docker compose down
  ```
- See running containers:
  ```bash
  docker ps
  ```
