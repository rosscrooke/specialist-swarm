# Hopper — Project Prompt

> Paste everything below the line into a fresh Claude Code session in an empty folder to
> rebuild this project. It captures the design as built **and** the fixes learned while
> testing it, so the rebuild doesn't repeat the same mistakes.

---

Build **Hopper**, a San Francisco–only prototype of an Uber-style app that plans
**combined multi-leg trips** — e.g. walk 1 mile → ride-hail → walk the last block — and
ranks them by **time, cost, and health** (active kcal, steps, hill climb).

## How to work

Use the superpowers skills in order: `brainstorming` (confirm scope with me, one question
at a time — keep it short, this spec answers most questions) → `writing-plans` →
`subagent-driven-development` with `test-driven-development` for every deterministic tool →
`verification-before-completion` (run tests AND drive the app in the browser) →
`requesting-code-review`. Don't commit until I say so.

## Stack

- Python 3.12, **Flask** backend, `anthropic` SDK. No database.
- Single-page frontend: plain HTML/CSS/JS + **Leaflet 1.9.4** with OSM tiles (load from
  unpkg with SRI hashes). No build step.
- Layout: `app/data.py` (fixtures), `app/tools.py` (deterministic tools),
  `app/agents.py` (swarm), `app/server.py` (API), `app/static/index.html`, `tests/`.
- Run: `PORT=5080 python3 -m app.server`.

## Core principle

**LLM agents do language; deterministic Python tools do every number.** No agent ever
computes a fare, time, distance, or calorie count. Every `Leg` records the tool that
produced it (`source`), and the Critic rejects any leg without one. The app must work
fully offline: with no `ANTHROPIC_API_KEY` (or `HOPPER_OFFLINE=1`), LLM agents fall
back to rules/templates and every number stays identical.

## Data fixtures (`data.py`, all approximate, offline)

- **~40 SF landmarks** `key → (name, lat, lon, elevation_ft)`: Ferry Building, Coit Tower
  (275 ft), Union Square, Powell/Montgomery/Embarcadero/Civic Center/Van Ness stations,
  Moscone, Salesforce Tower, Chinatown, Nob Hill (335), North Beach, Pier 39, Fisherman's
  Wharf, Lombard St (280), Ghirardelli, Marina Green, Palace of Fine Arts, Presidio,
  Japantown, Hayes Valley, Painted Ladies (220), Church & Duboce, Castro, Dolores Park,
  16th/24th St BART, Haight-Ashbury, Cole & Carl, 9th & Judah, Golden Gate Park, Ocean
  Beach, Twin Peaks (910), Glen Park, Balboa Park, Caltrain 4th & King, Oracle Park, Chase
  Center, SFO.
- **SF bounds** lat 37.70–37.835, lon −122.52 to −122.35; SFO is the one allowed exception.
- **Transit (7 lines)** as ordered stops + minutes per segment + headway: BART SFO line,
  Muni N Judah, T Third (Central Subway), F Market & Wharves, 39 Coit, Powell-Hyde cable
  car, 5 Fulton. Fares: Muni $2.85, cable car $8.00, BART $2.40 in-city / $10.95 to SFO.
- **Ride-hail — SIMULATED** (no Uber/Lyft API): base $2.50 + $1.35/mi + $0.32/min,
  × surge, min fare $9.00, + $2.95 booking fee; pickup wait 4 min (+3 under surge).
  Drive speed 11 mph (8 in rush hours, 30 mph for trips > 5 mi); drive circuity 1.30.
- **Surge zones** `(center, radius_mi, multiplier, hours, needs_event)`: Oracle Park
  0.45 mi ×1.9 and Chase Center 0.4 mi ×1.8 from 5–11 pm on event days; Financial
  District 0.6 mi ×1.4 from 4–7 pm daily. Surge applies at the **pickup** point.
- **Bay Wheels**: ~18 docks; $4.49 unlock incl. 30 min, classic +$3 per extra 15 min,
  e-bike +$0.30/min. Dock availability is a **deterministic hash of (dock, hour)** so
  demos and tests are reproducible.

## Deterministic tools (`tools.py`, unit-tested)

- `haversine_mi`; walk circuity 1.25.
- **Walk speed**: Tobler's hiking function `6·exp(−3.5·|grade+0.05|)` km/h, using the
  average grade between endpoints.
- **Walk kcal**: ACSM walking equation, *net* (resting excluded):
  `(0.1·S + 1.8·S·max(G,0)) · kg / 1000 · 5` per minute, S in m/min. Sanity: a flat
  mile at 80 kg ≈ 55–75 kcal.
- **Bike kcal**: (MET − 1) · kg · hours, MET 6.8 classic (+ hill load), 4.0 e-bike.
  Classic bike slows uphill: `10 mph · max(0.5, 1 − 6·grade)`; e-bike 13 mph.
- Steps = meters / 0.762. Climb = uphill elevation gain on active legs.
- `walk_leg`, `ride_leg`, `transit_leg` (works in both directions), `bike_leg`,
  `surge_at`, `dock_status`, `nearest`.
- `validate_trip(trip, req)` → list of reasons (see Critic).
- `pareto_front` on (min time, min cost, max kcal); `score_trips` = weighted sum of
  range-normalised time, cost, and (1 − kcal); `pick_options` (see Ranker).

## Agent swarm (`agents.py`)

| Agent | Kind | Job |
|---|---|---|
| Intent | `claude-haiku-5-5`, forced tool call | Free text → `TripRequest`. Origin/destination are an **enum of catalog keys** so it can't invent places. Regex+fuzzy fallback parser (aliases: giants→Oracle, warriors→Chase, airport→SFO; "cheap/steps/fast" → weights; "under $N" → budget; "rain", "game", "avoid hills"). |
| Context | rules | Rain → walk ≤ 0.5 mi/leg, ≤ 0.8 mi total, bikes off. After dark (≥ 9 pm or < 6 am) → walk ≤ 1.0 mi/leg. Event → stadium surge on. |
| Walk & Terrain | tools | Walk-only trip. |
| Ride-hail | tools | Ride-only; **walk-ahead** pickups (places ≤ 0.8 mi from origin and closer to the destination); **drop-early** points (≤ 0.6 mi from destination); walk→ride→walk combos. **Surge escape**: if the origin is surging, add the nearest pickups *outside* any surge zone within walking reach, in any direction. **Never** offer a pickup with higher surge than the origin. |
| Transit | tools | Per line: board at the 2 nearest stops (≤ 1.2 mi) that are **not farther from the destination than the origin** (no walking backwards to catch a train); alight at the 2 nearest stops to the destination; finish with a walk (≤ 1.2 mi) or a last-mile ride. |
| Micromobility | tools | Nearest docks with bikes / open docks; classic and e-bike variants. |
| Health | tools | Flags ≥ 150 ft climbs and % of daily step goal. |
| Critic | tools | Rejects: legs that don't connect; legs without a tool `source`; walk legs over the limit; uphill walk legs > **4%** average grade when "avoid steep" is on; total walk over the limit; over budget; wrong start/end; bikes in rain; **any paid trip slower than walking the whole way** (when that walk is ≤ 3 mi). |
| Ranker | tools | Pareto frontier → recommended = best weighted score; then fill up to 3 cards with the Fastest / Cheapest / Healthiest extremes, adding the ones the rider weighted **least** first (they're the useful trade-offs); merge labels when one trip wins several. **Signature card**: if no card is walk + ride, append the best-scoring walk + ride trip as a 4th "Walk + Ride" card, but only if it is ≤ 15 min slower than the door-to-door ride. |
| Explainer | `claude-haiku-5-5`, forced tool call | One sentence ≤ 20 words per card. Give it **pre-computed trade-offs** vs. the door-to-door ride ("saves $7.57", "+11 min", "+63 kcal") and tell it to copy them verbatim. **Grounding check**: every number in its sentence must appear in the facts it was given, and the sentence must be ≤ 28 words, otherwise fall back to the template. Strip a leading "Label:" since the card shows the label. |

- The orchestrator is plain Python (no LLM): Intent → Context → **parallel fan-out** of the
  4 route specialists (ThreadPoolExecutor) → dedupe by leg signature → Health → Critic →
  Ranker → Explainer.
- Every agent writes a trace row: agent, kind (llm / tools / rules / fallback / template),
  model, ms, tokens, detail.
- Anthropic client: `timeout=20, max_retries=1`; on any exception, log a fallback and
  continue. Honor `SSL_CERT_FILE` for corporate TLS.

## API

- `GET /api/places` → catalog + mode colors.
- `POST /api/plan` → `{request, origin_name, destination_name, options[], baseline,
  stats{candidates, feasible, frontier, ms, llm}, rejected[], trace[], plan_id}`.
  Errors return 422 with a friendly message (unknown place, outside SF, same place, no
  feasible trip).
- `POST /api/rerank {plan_id, weights}` → re-runs **only the Ranker** on cached feasible
  trips (small in-memory LRU of 50 plans); no specialists, no LLM calls.

## UI (`index.html`)

- Left panel (440 px) + full-height Leaflet map; under 820 px wide, stack with the map
  sticky on top. No horizontal scroll at 375 px. Light/dark via CSS variables.
- Inputs: plain-English box (Enter submits) **or** From/To dropdowns; leave-at hour;
  weather; budget; "Game / event day"; "Avoid steep hills"; profile (weight kg, max walk
  per leg / total). After a plan, write what the Intent agent understood back into the form.
- Sliders for Time / Cost / Health (0–3) + presets (Fastest, Cheapest, Healthiest,
  Balanced) → debounced `/api/rerank`.
- Trip cards: label chip, total cost, metrics (door-to-door min, kcal, steps, climb ft),
  a colored leg strip proportional to minutes, per-leg lines (mode, line name, distance,
  minutes + wait, cost, ⚡ surge, ⛰ uphill), the explanation, flags, and a **mock** "Book
  this trip" modal ("no real ride requested, no payment taken").
- Map: walk legs green dotted, ride dark solid, Muni red, BART blue, cable car brown,
  bike purple, e-bike magenta. Green origin dot, red destination dot, and a **permanent
  transfer marker** at every mode change ("Walk → Ride at Moscone Center"). Call
  `map.invalidateSize()` on resize and before `fitBounds`.
- Collapsible "Agent swarm trace" table and "Rejected by the Critic" list; mode legend;
  footer disclaimer that ride prices are simulated and calories are estimates.
- Escape all server strings before inserting into HTML.

## Tests (minimum)

Flat-mile kcal in range; uphill slower and higher kcal; Ferry Building → Coit Tower climbs
265 ft; ride min fare + fee; game-day surge only near the stadium in the evening; BART SFO
fare; transit leg reversible; Pareto drops a dominated trip; `pick_options` returns 3
distinct labelled trips; Critic rejects long walks and disconnected legs.

## Acceptance scenarios (check these in the browser)

| Trip | Expect |
|---|---|
| Ferry Building → Coit Tower, noon | Walk ~1 mi wins on cost; ride is Fastest; "avoid steep" removes the uphill walk |
| Union Square → SFO | BART ($10.95) beats the ~$35 ride |
| Oracle Park → Civic Center, 10 pm, game day | Walk + Ride card walks **out of** the surge zone (to Moscone) and rides for ~$12 vs ~$19.50 door to door; map shows "Walk → Ride at Moscone Center" |
| Chase Center → Union Square, 9 pm, game day | No pickup suggested inside the higher Oracle surge zone |
| Embarcadero → Ocean Beach, rain | Walk limits tighten, bikes rejected, N Judah wins |
| Castro → Fisherman's Wharf | Walk + Ride card is a short walk + ride, not a 45-min detour |
| "from Civic Center to Oracle Park at 6pm for the Giants game, cheap" | Intent agent fills origin, destination, 18:00, event, cost weight |

Every explanation must pass the number check (trace shows no "failed the number check").

## Constraints

- San Francisco only; decline other places gracefully.
- Secrets from environment variables only. No real PII; profile is local.
- No real ride bookings, no payments, no Uber/Lyft API calls. Label ride prices
  "simulated estimate" in the UI.
- Deterministic outputs for a given request (seeded availability, no randomness).

## Known limits (document in README, don't fix in v1)

Straight-line legs (no street routing), simplified transit with no transfers, simulated
ride prices, pseudo-random dock availability, average-grade hills. **Next steps:** OSM
routing (OSMnx/Valhalla), 511.org GTFS, live Bay Wheels GBFS, NWS weather, and a
`make eval` scorecard over 20 SF origin–destination pairs.
