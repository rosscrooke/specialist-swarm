# Hopper v2 — Complete Project Prompt

> Self-contained build prompt. Paste everything below the line into a fresh Claude Code
> session in an empty folder. No other files or prior context are needed.

---

# Build Hopper v2

**Hopper** is an Uber-style trip planner for **San Francisco** (city limits, plus trips
to and from **SFO airport**). Instead of selling one ride, it combines travel modes in one
trip — walk → ride-hail → walk, walk → BART → walk, bike → Muni → walk — and picks the
best combination for the rider's **Mode** and the **current weather**. It runs on
**Google Maps Platform** data and a **multi-agent specialist swarm** built on Claude.

Four Modes:

- ⚡ **Hustle** — fastest
- 💸 **Broke** — budget
- 🍸 **Bar Crawl** — hit cool bars (a multi-stop night out, not an A → B trip)
- 🔥 **Burn** — part transit, part workout

## 1. How to work

Use the superpowers skills, in order:

1. `superpowers:brainstorming` — this spec answers most questions; ask only about real
   gaps, one question at a time, then save the approved design to
   `docs/specs/<date>-hopper-v2-design.md`.
2. `superpowers:writing-plans` — bite-sized tasks, each with files, a failing test first,
   and an exact acceptance check.
3. `superpowers:subagent-driven-development` — one fresh subagent per task, reviewed
   before the next. Independent tasks (Google client, weather, bar scout, UI) may run in
   parallel.
4. `superpowers:test-driven-development` for every deterministic tool.
5. `superpowers:verification-before-completion` — tests pass AND the app is driven in a
   browser against every acceptance scenario.
6. `superpowers:requesting-code-review`.

Don't commit until I say so.

## 2. Core principle

**LLM agents do language; deterministic code does every number.** Fares, minutes,
distances, calories, grades, bar "cool scores", and rankings come from tools. Every leg
records the tool that produced it in `source` (e.g. `google.routes.walk`,
`fare_model.simulated`), and the Critic rejects any leg without one.

With no `ANTHROPIC_API_KEY` (or `HOPPER_OFFLINE=1`), LLM agents fall back to rule
parsers and sentence templates — **every number stays identical**.

## 3. Stack and layout

- Python 3.12, **Flask**, `anthropic` SDK, `httpx` for Google calls. No database.
- Frontend: one `index.html` with plain JS/CSS + **Google Maps JavaScript API**. No build step.
- Run: `PORT=5080 python3 -m app.server`.

```
app/
  server.py          Flask routes
  config.py          env vars, model ids, caps
  google_client.py   Routes, Route Matrix, Places, Geocoding, Elevation, Weather, Air Quality
                     (field masks, LRU cache, record/replay, per-plan call cap)
  modes.py           Mode presets + weather adjustment tables
  tools.py           Leg/Trip model, fare model, health math, Pareto, scoring, validation
  bars.py            Bar Crawl: search, filter, cool score, stop ordering, timeline
  agents.py          swarm + orchestrator + trace
  static/index.html
fixtures/google/     recorded Google responses for replay mode
tests/
README.md
```

## 4. The four Modes

The rider taps one Mode (big buttons). Each Mode is a preset of **weights + hard
constraints + weather tolerance**. Custom sliders (time / cost / health, 0–3) sit behind
an "Advanced" toggle.

| Mode | Goal | Weights (time · cost · health) | Hard constraints | Prefers |
|---|---|---|---|---|
| ⚡ **Hustle** | Fastest | 3 · 0.5 · 0 | Walk ≤ 0.4 mi/leg; arrive-by deadline is a hard cap; surge allowed | Ride-hail, BART, e-bike; walk only if it beats traffic |
| 💸 **Broke** | Budget | 0.5 · 3 · 0.5 | Walk ≤ 1.5 mi/leg, ≤ 2.5 mi total; ride-hail only if no other feasible trip (or total ≤ the rider's budget); trip ≤ 2.5× the fastest | Walk, Muni, BART, classic bike; walk out of surge zones |
| 🍸 **Bar Crawl** | Hit cool bars | Scores **stops**, not one trip (section 5) | 21+ gate; 2–5 stops; walk between bars ≤ 0.5 mi; **no bikes, scooters, or driving after the first stop**; last leg home is ride-hail or transit | One walkable cluster, open + highly rated bars, safe ride home |
| 🔥 **Burn** | Part transit / part workout | 0.5 · 0.5 · 3 | **≥ 1 transit leg AND active legs (walk/bike) ≥ 40% of door-to-door minutes**; walk ≤ 2.0 mi/leg; trip ≤ 1.75× the fastest; hills welcome | Walk or classic bike to a farther stop, transit for the long middle, walk the last stretch |

- **Burn is a hybrid, not a hike.** A pure-walk or pure-bike trip doesn't qualify. Cards
  show the split: "🔥 22 min active · 🚇 14 min transit · 190 kcal".
- Every trip card has a one-line **Mode fit** from the Explainer ("Hustle: 9 min faster
  than transit, worth the $14").

## 5. 🍸 Bar Crawl

**Inputs**: start point (or "use my location"), neighborhood (optional: Mission, North
Beach, Marina, Hayes Valley, SoMa, Castro, Lower Nob Hill, Haight…), number of stops
(2–5, default 3), vibe (any · cocktail · dive · brewery · wine · rooftop · live music ·
sports), start time, minutes per stop (default 45), optional end point (home).

1. **Age gate** — the rider confirms 21+ before any bar is shown; the API returns 403
   without `age_confirmed: true`.
2. **Find bars** — Places API (New) `searchNearby` (`includedTypes` such as `bar`, `pub`,
   `wine_bar`, `brewery`) or `searchText` ("cocktail bar in North Beach"). Field mask:
   `displayName, location, rating, userRatingCount, priceLevel, currentOpeningHours,
   regularOpeningHours, primaryType, editorialSummary, outdoorSeating, liveMusic,
   googleMapsUri`.
3. **Filter** (deterministic) — open from planned arrival through planned departure
   (handle hours that cross midnight); rating ≥ 4.3 with ≥ 100 reviews; matches the vibe;
   inside SF.
4. **Cool score** (deterministic, unit-tested) — `rating × ln(userRatingCount)` + vibe
   match bonus + editorial-summary bonus + variety bonus (penalise repeating the same
   `primaryType`) − price-level penalty when the rider asked for cheap.
5. **Order the stops** — choose the best N bars and their order by brute force (≤ 5
   stops ⇒ ≤ 120 orders per candidate set), maximising total cool score − walking minutes,
   with walking times from one `computeRouteMatrix` WALK call. Stay in one walkable
   cluster; allow one short transit hop only if two top bars are > 0.5 mi apart.
6. **Timeline** — arrive/leave time per stop; every bar must be open for its whole stop.
7. **Ride home** — last bar → end point by **ride-hail or transit only** (late-night /
   Owl lines after midnight); any walk after dark ≤ 0.3 mi.
8. **Output** — itinerary card: per stop name, type, ★ rating, price level ($–$$$$),
   "why it's cool" (Explainer, grounded in the place's summary/attributes), arrive/leave
   times, walk to the next stop; then the ride-home leg. Map: numbered pins, walking route
   between bars, ride-home polyline. Also return one **alternate crawl** (different vibe or
   neighborhood).

**Safety and tone**: footer "Drink responsibly. Never drive." No drink counts, drinking
games, or "shots" suggestions. Suggest a food stop when the crawl runs > 2 hours. Show
price only as Google's price level — never invented dollar amounts.

## 6. Weather (first-class input)

Fetch current conditions + hourly forecast for the departure window from the **Google
Weather API**, air quality from the **Google Air Quality API**, and sunset time from the
Weather API. The Context agent applies per-Mode adjustments:

| Condition | Hustle | Broke | Bar Crawl | Burn |
|---|---|---|---|---|
| Rain (precip prob ≥ 50% or rate > 0) | walk ≤ 0.2 mi | walk ok with ☔ flag, bikes off | bars ≤ 0.25 mi apart; skip rooftop/patio-only bars | more transit share, walk ok with ☔ flag, bikes off |
| Wind > 20 mph | bikes off | bikes off | deprioritise rooftops | classic bike off, e-bike ok |
| Fog / cold (< 55 °F) | — | — | deprioritise outdoor seating | flag; prefer lit routes after dark |
| Heat ≥ 85 °F or UV ≥ 7 | — | flag | boost outdoor seating / rooftops | cap active time at 30 min; hydration note |
| AQI ≥ 100 | — | flag | indoor bars only | shorter active legs, more transit |
| After dark | — | walk ≤ 1.0 mi | walk between bars ≤ 0.5 mi on busy streets; home leg ride/transit | walk ≤ 1.0 mi |

- Rain also adds ×1.3 ride-hail surge city-wide and +3 min pickup wait.
- The UI shows a weather strip (icon, °F, precip %, wind, AQI) and what it changed:
  "🌧 Rain at 6 pm — bike options hidden, walks shortened."
- Cache weather 10 min per ~1 km grid cell. If the API fails, show a manual weather
  selector and note the fallback in the trace.

## 7. Google Maps Platform

| Need | API | Notes |
|---|---|---|
| Map, markers, polylines | **Maps JavaScript API** (Advanced Markers) | Browser key, HTTP-referrer restricted |
| From/To search | **Places API (New)** Autocomplete + Place Details | Bias to SF; reject places outside SF (SFO allowed) |
| Bar Crawl stops | **Places API (New)** `searchNearby` / `searchText` | Field-masked |
| Free text → coordinates | **Geocoding API** | Intent agent's `geocode` tool |
| Walk / bike / drive / transit legs | **Routes API** `computeRoutes`, `travelMode` = `WALK`, `BICYCLE`, `DRIVE` (`routingPreference: TRAFFIC_AWARE`), `TRANSIT` | Always send `X-Goog-FieldMask` with only the needed fields |
| Many pickup / drop-off / bar candidates | **Routes API** `computeRouteMatrix` | Score 10–25 candidates in one call |
| Transit lines, stops, fares | `computeRoutes` `TRANSIT` (`transitDetails`, `travelAdvisory.transitFare`, up to 3 alternatives) | Fallback fares below if missing |
| Hills | **Elevation API**, sampled along each walk/bike polyline (~every 50 m) | Per-segment grade, climb, steepest block |
| Weather, air | **Weather API**, **Air Quality API** | Section 6 |

**Keys, cost, caching**

- `GOOGLE_MAPS_SERVER_KEY` — server only (Routes, Places, Geocoding, Elevation, Weather,
  Air Quality). `GOOGLE_MAPS_BROWSER_KEY` — Maps JS + Autocomplete only, referrer-restricted,
  served to the page via `GET /api/config`. Both from env vars; never hard-coded, logged,
  or sent to Claude.
- Cache every Google response (in-memory LRU + optional disk) keyed by coordinates rounded
  to ~50 m + travel mode + 5-minute departure bucket. Count cache hits in the trace.
- **Hard cap: ≤ 12 Google calls per plan.** Prune candidates with `computeRouteMatrix`
  before calling `computeRoutes` for finalists only.
- **Record/replay**: `HOPPER_RECORD=1` saves responses to `fixtures/google/`;
  `HOPPER_REPLAY=1` serves them, so tests and demos need no key, network, or spend.

## 8. Pricing and health (deterministic, in `tools.py`)

**Ride-hail — SIMULATED** (no Uber/Lyft API; label every price "simulated estimate"):
- Distance and duration from Google `DRIVE` (`TRAFFIC_AWARE`).
- Fare = max((2.50 + 1.35 × miles + 0.32 × minutes) × surge, 9.00) + 2.95 booking fee.
- Pickup wait 4 min (+3 under surge or rain).
- Surge at the **pickup** point: Oracle Park ×1.9 (0.45 mi radius) and Chase Center ×1.8
  (0.4 mi) on event nights 5–11 pm; Financial District ×1.4 (0.6 mi around Montgomery St)
  4–7 pm daily; rain ×1.3 everywhere; take the max multiplier.

**Transit fares** — prefer Google's `transitFare`; fallback: Muni bus/rail $2.85, cable
car $8.00, BART $2.40 within SF, $10.95 to/from SFO.

**Bay Wheels** — live station status from the public GBFS feed (no key). Price: $4.49
unlock including 30 min; classic +$3.00 per extra 15 min; e-bike +$0.30/min.

**Health**
- Walk kcal (net, resting excluded), ACSM walking equation per polyline segment:
  `kcal/min = (0.1·S + 1.8·S·max(G, 0)) × kg / 1000 × 5`, S = speed in m/min from
  Google's duration, G = segment grade from Elevation. Sanity: flat mile at 80 kg ≈ 55–75 kcal.
- Bike kcal = (MET − 1) × kg × hours; MET 6.8 classic (+ hill load from grade), 4.0 e-bike.
- Steps = walk meters / 0.762. Climb = uphill elevation gain on active legs.
- Active minutes = walk + bike minutes. Burn's active share = active / door-to-door minutes.
- Default profile: 75 kg, 8,000-step goal; editable, stored only in the browser.

## 9. Data model

```python
Leg:  mode (walk|ride|muni|bart|cable|bike|ebike), frm, to (name + lat/lng), distance_mi,
      minutes, wait_min, cost, kcal, steps, climb_ft, max_grade, line, surge,
      polyline, rain_exposed, source
Trip: legs[], specialist, id, flags[]; derived total_min, cost, kcal, steps, walk_mi,
      active_min, active_share, climb_ft, transfers, signature
Crawl: stops[{place, arrive, leave, cool_score, why}], walks[Leg], ride_home[Leg], totals
```

## 10. Agent swarm

| Agent | Kind | Job |
|---|---|---|
| **Intent** | `claude-haiku-5-5`, forced tool call | Free text → `TripRequest` or `CrawlRequest`: places (via `geocode`), leave-at / arrive-by, **Mode** ("late", "asap" → Hustle; "cheap", "broke" → Broke; "bars", "drinks", "night out", "crawl", "bar hop" → Bar Crawl with stops / vibe / neighborhood; "workout", "steps", "exercise" → Burn), budget. Regex + fuzzy fallback when offline. |
| **Context** | tools + rules | Weather, AQI, sunset, event night → per-Mode constraint adjustments (section 6). |
| **Walk & Terrain** | tools | Google WALK route + Elevation profile; per-segment grade; steepest block. |
| **Ride-hail** | tools | Pickups: walk-ahead points every ~0.25 mi along the walking polyline toward the destination, plus **surge-escape** points outside every surge zone within the Mode's walk limit. **Never** a pickup with higher surge than the origin. Drop-offs: door-to-door, plus early drop-offs for Burn and Broke. Prune with `computeRouteMatrix` DRIVE, then price. Also prices the Bar Crawl ride home. |
| **Transit** | tools | Google TRANSIT alternatives. Don't walk away from the destination to board. Add a last-mile ride when the final walk exceeds the Mode limit. For Burn, also board 1–2 stops later along the walk or alight 1–2 stops early to reach 40% active. |
| **Micromobility** | tools | GBFS docks with bikes near the start and open docks near the end; Google BICYCLE route; classic and e-bike variants. |
| **Bar Scout** | tools (+ Haiku for "why it's cool") | Bar Crawl steps 2–7. The LLM only writes the one-line "why it's cool" from the place's summary and attributes, with the grounding check. |
| **Health** | tools | kcal, steps, climb, active share, % of step goal; flags ≥ 150 ft climbs. |
| **Critic** | tools | Rejects: legs that don't connect; unsourced numbers; Mode + weather constraint violations; over budget; misses the arrive-by deadline; **any paid trip slower than walking the whole way** (walk ≤ 3 mi); Burn without a transit leg or under 40% active; Bar Crawl bike/drive legs after stop 1 or a bar closed during its stop; places outside SF (except SFO). |
| **Ranker** | tools | Pareto front on (min time, min cost, max kcal) → weighted, range-normalised score with the Mode weights → **Best for <Mode>** + up to 2 contrasting cards (the extremes the Mode weights least: e.g. Broke also shows the fastest trip, "Hustle would ride for $16, 12 min faster") + a **Walk + Ride** card if none is shown and the best walk + ride trip is ≤ 15 min slower than a direct ride. Bar Crawl: best itinerary + one alternate. |
| **Explainer** | `claude-haiku-5-5`, forced tool call | One sentence ≤ 20 words per card. It receives **pre-computed** trade-offs vs. the door-to-door ride ("saves $7.57", "+11 min", "+63 kcal") plus the weather note, and must copy numbers verbatim. **Grounding check**: every number in its output must appear in the facts it was given and the sentence must be ≤ 28 words, else use the template. Strip a leading "Label:". |

- The **orchestrator is plain Python**: Intent → Context → specialists **in parallel**
  (or Bar Scout for Bar Crawl) → Health → Critic → Ranker → Explainer.
- **Trace** every step: agent, kind (llm / tools / rules / fallback / template), model,
  ms, tokens, Google calls + cache hits, detail.
- Anthropic client: `timeout=20, max_retries=1`; on any error log a fallback and continue.
  Honor `SSL_CERT_FILE` for corporate TLS proxies.
- Switching Mode re-runs **only the Ranker** on cached feasible trips — unless the new
  Mode's constraints are looser than the cached plan's, then re-plan.

## 11. API

- `GET /api/config` → `{browser_key, map_center, bounds}`.
- `POST /api/plan {query? | origin, destination, depart_at | arrive_by, mode, budget?, profile}`
  → `{request, weather{now, at_departure, aqi, sunset, adjustments[]}, options[], baseline,
  stats{candidates, feasible, frontier, google_calls, cache_hits, ms, llm}, rejected[],
  trace[], plan_id}`.
- `POST /api/crawl {start, neighborhood?, stops, vibe, start_at, minutes_per_stop, end?,
  budget_conscious?, age_confirmed}` → `{weather, itinerary{stops[], walks[], ride_home},
  alternate, stats, trace}`; 403 without `age_confirmed`.
- `POST /api/rerank {plan_id, mode | weights}` → `{options, trace}` (in-memory LRU of 50 plans).
- `GET /api/weather?lat&lng` (debug).
- Friendly 422s: outside SF, same place, no feasible trip ("Burn found no transit +
  workout combo under 1.75× the fastest time — try Broke?"), no open bars for that vibe.

## 12. UI

- **Google Map** full height on the right; under 820 px wide, map stacks on top (sticky)
  and the panel scrolls below. No horizontal scroll at 375 px. Light/dark via CSS variables.
- Panel: plain-English box ("late for a meeting at Salesforce Tower from the Castro"),
  From/To with Places Autocomplete + "Use my location", leave-now / arrive-by picker,
  budget, profile (weight, max walk).
- **Mode bar**: ⚡ Hustle · 💸 Broke · 🍸 Bar Crawl · 🔥 Burn — big, thumb-friendly; one tap
  re-ranks trip Modes. "Advanced" reveals sliders. After a plan, write what the Intent
  agent understood back into the form.
- **Weather strip** with what it changed.
- **Trip cards**: "Best for <Mode>" chip, cost, door-to-door minutes, kcal, steps, climb,
  Burn's active/transit split, colored leg strip proportional to minutes, per-leg lines
  (mode, line/route name, distance, minutes + wait, cost, ⚡ surge, ⛰ steepest block %,
  ☔ rain-exposed), explanation, Mode-fit line, mock **Book** modal ("no real ride was
  requested, no payment taken").
- **Bar Crawl**: picking it swaps From/To for the crawl form (start, neighborhood, stops,
  vibe chips, start time, home) behind a 21+ confirm; results show the itinerary timeline
  and numbered bar pins.
- **Map**: real Google polylines per leg — walk dotted green, ride dark solid, Muni red,
  BART blue, cable car brown, bike purple, e-bike magenta; origin/destination markers;
  **transfer markers** with permanent labels ("Walk → Ride at 4th & Townsend"); surge
  zones as translucent circles; rain badge.
- Collapsible **Agent swarm trace** (with Google calls + cache hits) and **Rejected by
  the Critic**. Footer: ride prices simulated; calories are estimates; booking is a mock;
  "Drink responsibly. Never drive." on Bar Crawl.
- Escape every server string before inserting it into HTML.

## 13. Tests (replay fixtures only — no live Google calls)

- Health: flat-mile kcal in range; per-segment uphill raises kcal; steps; active share.
- Pricing: ride min fare + fee; event surge only near the stadium in the evening; FiDi
  rush surge; rain surge; max of overlapping multipliers; transit fallback fares.
- Modes: constraint tables; weather → adjustment mapping for every cell of section 6.
- Critic: each rejection rule, including Burn's transit + 40% rule and "slower than walking".
- Ranker: Pareto drops dominated trips; "Best for Mode" changes with the Mode; Walk + Ride
  card rules.
- Explainer: grounding check accepts copied numbers, rejects invented ones, strips labels.
- Bar Crawl: cool score ordering; open-for-whole-stop across midnight; ordering minimises
  walking; no bike/drive after stop 1; ride home present; rain shrinks the cluster;
  age gate 403.
- Google client: field masks sent; parsing; errors → fallback; cache keys; call cap enforced.

## 14. Acceptance scenarios (record fixtures, then verify in the browser)

| Request | Mode | Weather | Expect |
|---|---|---|---|
| Ferry Building → Coit Tower | Burn | clear | Walk part way + 39 Coit or F line; has a transit leg; ≥ 40% active; steepest block shown |
| Embarcadero → Ocean Beach | Burn | clear | Walk/bike to a later N Judah stop, transit for the long middle, walk to the beach |
| Union Square → SFO | Broke | any | BART (~$10.95) beats a ~$35+ ride |
| Union Square → SFO | Hustle | clear, 5 pm | Traffic-aware ride vs BART, honest about rush hour |
| Oracle Park → Civic Center, 10 pm, game night | Broke | clear | Walks out of the surge zone then rides, or transit/bike if cheaper |
| Oracle Park → Civic Center, 10 pm, game night | Hustle | rain | Bikes hidden, short walk, accepts surge |
| Mission Dolores → Painted Ladies | Burn | AQI 150 | Active share reduced, more transit; trace shows the AQI adjustment |
| North Beach, 3 stops, cocktail, 8 pm, home Hayes Valley | Bar Crawl | clear | 3 open, ≥ 4.3★ cocktail bars in one walkable cluster; timeline; ride home |
| Mission, 4 stops, any vibe, 9 pm | Bar Crawl | rain | ≤ 0.25 mi hops; no rooftop/patio-only bars; transit or ride home |
| "late for a meeting at Salesforce Tower from the Castro" | inferred Hustle | live | Intent picks Hustle and an arrive-by deadline |
| "bar hop in the Marina tonight, 3 spots, then home to the Sunset" | inferred Bar Crawl | live | Intent fills neighborhood, stops, home; age gate shown |

Every explanation passes the grounding check; every plan stays within 12 Google calls.

## 15. Constraints

- Scope: San Francisco city limits + SFO airport only; decline anything else politely.
- Secrets only from env vars; keys restricted; never logged or sent to Claude.
- No real ride bookings, payments, or Uber/Lyft API calls.
- No rider PII beyond a local profile (weight, step goal); location used only for the
  current request.
- Bar Crawl: 21+ gate, responsible-drinking footer, no driving or bikes after stop 1.
- Deterministic results in replay mode.

## 16. Definition of done

- `python3 -m app.server` starts the app.
- Replay mode demos every acceptance scenario with no keys.
- Live mode works with `GOOGLE_MAPS_SERVER_KEY`, `GOOGLE_MAPS_BROWSER_KEY`, and
  `ANTHROPIC_API_KEY`.
- All tests pass.
- README covers: which Google APIs to enable and how to restrict the keys, the agent
  swarm diagram (Mermaid), cost controls (field masks, matrix pruning, cache, call cap),
  record/replay, and known limitations (simulated ride prices, Google transit-fare gaps,
  bar data freshness).
