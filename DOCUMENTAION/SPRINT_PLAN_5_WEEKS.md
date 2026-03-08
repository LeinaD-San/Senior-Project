# trAgent — 5-Week Sprint Plan

Baseline goal: make the website **better**, **cleaner**, and more **innovative**, while stabilizing the core demo flow (Home → Plan → Results → Planner → Save/Open/Edit).

## Week 1 — AI (Innovation Sprint)

**Goal**: Introduce an AI-assisted planning feature that feels “smart”, not random.

**Deliverables**
- AI itinerary suggestions endpoint (server-side) that can:
  - Generate a day-by-day plan from destination + interests + days
  - Suggest “themes” per day and recommended stop counts
- UI option in plan/results:
  - “AI Assist” toggle or button
  - Clear explanation: “AI suggests, you choose”

**Implementation ideas**
- Add `/ai/itinerary` as the central AI endpoint (you already have a stub) and upgrade it to:
  - Use a real LLM provider OR a rules+heuristics “AI-like” model if keys aren’t available
  - Output structured JSON matching your trip/day/stop format
- Combine AI with Google Places:
  - AI generates queries/categories per day
  - Backend fetches places via Places API

**Success criteria**
- User can press “AI Assist” and receive a usable plan
- Plan still allows manual editing and saving

## Week 2 — UX & Visual Polish Sprint

**Goal**: Make the app feel cohesive, modern, and easy to understand.

**Deliverables**
- Consistent navigation across pages (Home / Planner / Account)
- Clear step-by-step flow indicators (e.g., Step 1: Plan → Step 2: Results → Step 3: Planner)
- Better feedback states:
  - Loading spinners while searching
  - Helpful error messages (missing key, no results)
  - Empty states for “My Saved Trips”
- Mobile-first layout fixes (spacing, tap targets, sticky actions)

**Success criteria**
- A first-time user can complete the flow without guidance
- Visual design looks consistent across all pages

## Week 3 — Reliability & Collaboration Sprint

**Goal**: Reduce “it works on my machine” issues and make setup predictable.

**Deliverables**
- Setup hardening:
  - Clear `.env.example` guidance
  - DB port consistency (`5433` vs `5432`) documented
  - One command to reset local DB for fresh demos
- Basic automated checks:
  - Add a small smoke-test script (curl-based) for auth + trips
  - Add minimal pytest API tests (auth + trips CRUD)

**Success criteria**
- Any teammate can run the app from scratch in <15 minutes
- Auth/register/login and save/open/delete trips works reliably

## Week 4 — Features that Improve Real Use (Value Sprint)

**Goal**: Add features that make the itinerary genuinely useful during a trip.

**Deliverables**
- “During trip” mode:
  - Map link / directions link per stop
  - Mark complete + progress meter per day
- Better stop details:
  - Place details modal (photos, phone, website) via `/places/{place_id}`
  - Optional: show place photo thumbnails in search results
- Trip management:
  - Rename trip
  - Duplicate trip

**Success criteria**
- Planner becomes a practical checklist + guide during the day

## Week 5 — Demo & Storytelling Sprint

**Goal**: Prepare a polished final demo and narrative.

**Deliverables**
- Demo script:
  - Exact steps + sample destination + interests
  - Backup plan if Google API rate-limits (fallback data)
- Performance pass:
  - Cache Places results per query (short TTL)
  - Reduce duplicate API calls
- Presentation materials:
  - Before/after screenshots
  - Architecture diagram
  - Short “what we learned” slide

**Success criteria**
- Demo can be repeated multiple times without troubleshooting
- Clear explanation of innovation (AI assist + usability)

## Suggested Next Steps (Immediate)

- Decide AI approach for Week 1 (real LLM vs heuristic “AI-like” output)
- Add place photo thumbnails in results (quick UX win)
- Add a “Return to where you were” auth redirect on all pages consistently
