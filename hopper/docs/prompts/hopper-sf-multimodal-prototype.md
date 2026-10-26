# Build Prompt — Hopper (SF multimodal commute prototype)

> Paste everything below the line into a fresh Claude Code session, in an empty project folder.

---

You are building **Hopper**, a working prototype of an Uber-like app that does NOT just sell a ride. It plans **combined, multi-leg trips** — e.g. walk 1 mile → ride-hail 2.5 miles → walk the last 0.3 mile — and lets the rider choose the trade-off between **time, cost, and health**. Scope is **San Francisco only**.

## How you must work (superpowers workflow — non-negotiable)

1. **`superpowers:brainstorming` first.** Ask me clarifying questions ONE at a time before designing anything. Cover at least: who the target rider is, which modes are in v1, how health is personalized, what "booking" means in a prototype, and what the demo must show. Then write the approved design to `docs/specs/YYYY-MM-DD-hopper-design.md`.
2. **`superpowers:writing-plans`** — turn the spec into a bite-sized implementation plan in `docs/plans/`. Each task: files touched, test first, exact acceptance check.
3. **`superpowers:using-git-worktrees`** — implement on a feature branch in its own worktree.
4. **`superpowers:subagent-driven-development`** — execute the plan with one fresh subagent per task, reviewing each task's output before moving on. Independent tasks (e.g. the specialist tools below) may be dispatched in parallel via `superpowers:dispatching-parallel-agents`.
5. **`superpowers:test-driven-development`** for every deterministic tool (routing, cost, calories, Pareto ranking).
6. **`superpowers:verification-before-completion`** — no "done" claims without running the tests and the demo.
7. **`superpowers:requesting-code-review`** before finishing; then `superpowers:finishing-a-development-branch`.

## Product requirements

**Modes (combinable in one trip):**
- Walk (with SF hill/elevation awareness — this matters enormously in SF)
- Ride-hail (UberX-style; **simulated** — see constraints)
- Muni (bus, Metro light rail, cable car) and BART
- Bay Wheels bike/e-bike share
- (Stretch) Drive + park, then walk

**Each trip option shows:**
- Leg-by-leg timeline (mode icon, distance, duration, transfer waits)
- Total door-to-door time, total cost ($), calories burned (kcal), steps, active minutes, total climb (ft)
- A one-line plain-English "why this route" explanation

**Rider controls:**
- Weight sliders: Time ↔ Cost ↔ Health (or presets: "Fastest", "Cheapest", "Healthiest", "Balanced")
- Max walking distance per leg, max total walk, avoid steep hills (grade cap), accessibility mode (no stairs, minimal walking)
- Profile: body weight (for calorie math), daily step goal
- "Arrive by" / "Leave now"

**Output:** always return **3 options on the Pareto frontier** (no option should be strictly worse than another on all of time, cost, health), plus the single recommended option for the rider's weights.

## Multi-agent architecture — specialist swarm

Build an **orchestrator + specialist swarm** using the Anthropic API (Python SDK, tool use) or the Claude Agent SDK.

**Golden rule: LLM agents plan, negotiate, and explain; deterministic Python tools do every number.** No agent may compute a fare, a calorie count, a distance, or a travel time in its own head — it must call a tool. Unit-test every tool.

| Agent | Model | Responsibility | Tools it owns |
|---|---|---|---|
| **Orchestrator** | `claude-opus-5-5` | Parses the trip request, fans out to specialists in parallel, merges candidate legs into full trips, resolves conflicts, calls the Critic | `dispatch_specialists`, `assemble_trip` |
| **Intent agent** | `claude-haiku-5-5` | Turns free text ("get me to Oracle Park by 6:30, I want to get some steps in, under $15") into a structured `TripRequest` (origin, dest, time constraint, weights, limits) | `geocode_sf` |
| **Walk & Terrain specialist** | `claude-haiku-5-5` | Walking legs; flags steep segments; proposes "walk to a better pickup point" options | `walk_route`, `elevation_profile` |
| **Transit specialist** | `claude-haiku-5-5` | Muni/BART legs from GTFS; real schedules, transfers, fares | `transit_route`, `transit_fare` |
| **Ride-hail specialist** | `claude-haiku-5-5` | Ride legs; chooses smart pickup/drop-off points (e.g. avoid one-way-street detours, surge zones) | `ride_estimate` (simulated), `pickup_point_candidates` |
| **Micromobility specialist** | `claude-haiku-5-5` | Bay Wheels legs: dock availability, e-bike vs classic | `bikeshare_status`, `bike_route` |
| **Health specialist** | `claude-haiku-5-5` | Calories, steps, active minutes, hill effort; daily-goal progress | `calories`, `steps` |
| **Context specialist** | `claude-haiku-5-5` | Weather/fog/rain, time of day, daylight; downgrades long walks in rain or after dark | `weather_now` |
| **Ranker** | `claude-sonnet-5-5` | Builds the Pareto frontier, applies rider weights, picks 3 options + recommendation | `pareto_rank` (deterministic) |
| **Critic / Verifier** | `claude-sonnet-5-5` | Rejects infeasible trips: impossible transfers, walking legs over the rider's limit, legs that don't connect, closed docks, numbers not backed by a tool call | `validate_trip` |
| **Explainer** | `claude-haiku-5-5` | Writes the "why this route" line and the trade-off summary ("+4 min, saves $11, +210 kcal") | — |

**Swarm protocol:**
- Orchestrator fans out to specialists **in parallel** (asyncio), each returns candidate legs as typed JSON (Pydantic models: `Leg`, `Trip`, `TripRequest`, `Metrics`).
- Orchestrator assembles combinations (walk→ride→walk, walk→Muni→walk, bike→BART→walk, ride-only, walk-only, etc.), capped at a sane number of candidates.
- Critic validates; failed trips go back to the owning specialist once with the reason, then are dropped.
- Ranker returns the Pareto set; Explainer annotates.
- Log every agent call (model, tokens, latency, cost) — show a per-request trace in a debug panel.

## Data & integrations (SF)

- **Street network & walking/biking routes:** OpenStreetMap SF extract with a local router (e.g. OSMnx + NetworkX, or OSRM/Valhalla in Docker). Prefer local over paid APIs.
- **Elevation:** USGS 3DEP / OpenTopoData or a cached SF DEM — needed for hill-adjusted walk time and calories.
- **Transit:** 511 SF Bay GTFS static (Muni + BART) — free API key from 511.org via env var `FIVE11_API_KEY`; cache the feed locally.
- **Bike share:** Bay Wheels public GBFS feed (no key).
- **Weather:** api.weather.gov (NWS, no key).
- **Ride-hail:** **simulated** pricing model — base fare + per-mile + per-minute + booking fee + time-of-day surge multiplier, with drive times from the local road router. Put the coefficients in a config file and label every ride price in the UI as "estimate (simulated)". Do NOT call real Uber/Lyft APIs.
- **Offline / demo mode:** every external feed has a cached fixture so the demo runs with no network.

## Health math (deterministic, tested)

- Walking calories via MET × body weight (kg) × hours, with MET adjusted for grade (flat ≈ 3.5, brisk ≈ 4.3, uphill scaled by grade). Cycling: classic vs e-bike METs.
- Steps from distance and a stride-length estimate (configurable).
- Walking speed slows on uphill grade (e.g. Tobler's hiking function).
- Show health numbers as estimates; no medical claims.

## Prototype UI

- Web app: FastAPI (or Flask) backend + a single-page frontend with **Leaflet + OSM tiles**, centered on San Francisco.
- Search bar accepts free text or two map pins.
- Results: 3 trip cards, each with a color-coded leg strip (walk / ride / Muni / BART / bike), totals row (time · $ · kcal · steps · climb), and the explanation line. Clicking a card draws the legs on the map.
- Weight sliders re-rank instantly (re-run only the Ranker, not the whole swarm).
- "Book" button is a **mock**: shows a confirmation screen for the ride leg; no real booking or payment.
- Mobile-width layout must work (riders use phones).

## Evaluation harness (build alongside the app)

- A gold set of **20 SF origin–destination pairs** covering hard cases, e.g.:
  - Ferry Building → Coit Tower (steep final climb — should prefer ride for the hill)
  - Mission Dolores Park → Painted Ladies (walk vs. short ride)
  - Civic Center → Oracle Park at 6 pm on a game day (surge — transit should win on cost)
  - Embarcadero → Ocean Beach (long; BART/Muni + walk vs. ride)
  - Union Square → SFO (BART should dominate on cost)
  - Rainy evening variant of a long-walk trip (Context agent should downgrade walking)
- Metrics per run: % trips feasible (Critic pass), Pareto validity, time/cost error vs. fixtures, p50 latency, LLM cost per request.
- `make eval` prints a scorecard; commit a baseline and track improvements.

## Constraints

- San Francisco only — reject or gracefully decline trips outside the SF city boundary.
- All secrets from environment variables; never hard-code keys.
- No real rider PII; profiles are local and synthetic for the demo.
- No real ride bookings, no payments.
- Deterministic seed for simulated surge/availability so the eval is reproducible.
- Keep it a prototype: favor clarity and a great demo over production scale.

## Definition of done

- `make dev` starts the app; a demo script walks through 3 showcase trips end-to-end.
- All tool unit tests pass; `make eval` produces a scorecard with ≥ 90% feasible trips.
- README with architecture diagram (Mermaid) of the agent swarm, setup steps, and known limitations.

Start now with the brainstorming step — ask me your first clarifying question.
