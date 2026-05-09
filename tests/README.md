# Tests

Run from the project root:

```bash
# install once
pip install -r requirements-dev.txt

# run everything
pytest

# run one file
pytest tests/test_auth.py

# run one test
pytest tests/test_auth.py::test_register_lowercases_email -v
```

## What gets tested

| File | Covers |
| --- | --- |
| `test_helpers_basic.py` | password hashing, interest encode/decode, `validate_hhmm`, `validate_time_range`, bearer parsing, HH:MM ↔ minutes, `parse_clock_to_minutes`, `parse_google_duration_to_minutes`, `estimate_price_score`, `get_real_weekday_index` |
| `test_dedupe_and_ranking.py` | `dedupe_places`, `dedupe_places_by_id`, `score_place_for_profile`, `rank_places_for_profile`, `score_place` |
| `test_itinerary_helpers.py` | pace/budget helpers, slot prefs, recommended-interests, interest-query builder, visit-time estimates, hours parsing, `is_place_open_for_time`, `distribute_places_across_days`, `build_balanced_itinerary` |
| `test_auth.py` | `/auth/register`, `/auth/login`, `/auth/logout`, `/me`, expired-session handling |
| `test_trips.py` | `POST/GET/PATCH/DELETE /trips`, ownership checks, validation |
| `test_trip_items.py` | adding, updating, deleting, reordering trip items; time-range validation |
| `test_places.py` | `/places/search`, `/places/autocomplete`, `/places/details`, `/places/nearby`, `/geo/reverse`, `/places/recommended`, `/ai/replace-stop`, `/ai/itinerary` (Google Maps and OpenAI calls are stubbed) |
| `test_misc_endpoints.py` | `/health`, `/config/maps`, page-serving routes, `/ai/test` |

## How the test environment works

`tests/conftest.py` does the setup:

- forces `DATABASE_URL=sqlite:///:memory:` before importing app modules,
- builds a single in-memory SQLite engine with `StaticPool` so the schema persists across the run,
- swaps `database.engine` / `database.SessionLocal` (and the same names in `main`) to that test engine,
- overrides FastAPI's `get_db` dependency,
- recreates tables from `models.Base.metadata` before every test (so each test starts clean),
- attaches UTC tzinfo on load for `User` / `SessionToken` (SQLite drops it; Postgres in prod doesn't, so this only affects tests),
- sets dummy `GOOGLE_MAPS_API_KEY` env vars so endpoints don't 500 on the "not configured" branch.

Outbound HTTP calls (Google Maps, Google Routes) are mocked via the `fake_httpx` fixture in `test_places.py`, which replaces `httpx.AsyncClient` with a fake whose `.get` / `.post` pop pre-canned responses off a queue. **No real network calls are made by the test suite.**

OpenAI is also never hit: `main.openai_client` is patched to `None` for the one test that exercises `/ai/test`.

## Notes for new tests

- Use the `client` fixture for HTTP, the `db_session` fixture if you need to read/write the DB directly, and `auth_headers` / `registered_user` to act as a logged-in user.
- For any endpoint that calls Google, push canned `_FakeResponse(...)` objects onto `fake_httpx.responses` in the order the endpoint will consume them.
- The startup event in `main.py` is **not** triggered (we don't use `TestClient` as a context manager) because its `ALTER TABLE ... IF NOT EXISTS` statements are Postgres-only and would error on SQLite. Tables come from `models.Base.metadata.create_all` in the autouse fixture.
