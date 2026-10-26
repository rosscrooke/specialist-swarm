"""Hopper specialist swarm.

Language work (understanding the request, explaining the result) goes to Claude.
Number work (routes, fares, calories, ranking, validation) goes to deterministic
tools. Specialists fan out in parallel; the Critic and Ranker gate what the rider sees.
Every agent call is logged to the trace shown in the UI's debug panel.
"""
import difflib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import bikes, five11, geo, guard, modes, osrm, tools, weather, world
from .data import BIKE_DOCKS, PLACES, TRANSIT_LINES
from .live import FeedError

INTENT_MODEL = os.environ.get("HOPPER_INTENT_MODEL", "claude-haiku-5-5")
EXPLAIN_MODEL = os.environ.get("HOPPER_EXPLAIN_MODEL", "claude-haiku-5-5")
SF_TZ = ZoneInfo("America/Los_Angeles")
MAX_REALTIME_LOOKUPS = 4      # unique (line, board, alight) per plan — protects 511's 60/hr
MAX_ROUTED_LEGS = 60          # unique street legs per plan sent to OSRM (cached for a day)
ROUTING_BUDGET_S = 8.0        # wall-clock cap on OSRM per plan


def sf_hour():
    return datetime.now(SF_TZ).hour

DEFAULTS = {"hour": "now", "weather": "live", "event": False, "weight_kg": 75,
            "weights": {"time": 1.0, "cost": 1.0, "health": 1.0},
            # Plans use the loosest Mode limits so every Mode can re-rank the cached trips.
            "max_walk_leg_mi": 2.0, "max_total_walk_mi": 3.0, "avoid_steep": False,
            "mode": "hustle",
            "max_cost": None, "step_goal": 8000}


def _llm():
    if os.environ.get("HOPPER_OFFLINE") == "1" or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(timeout=20, max_retries=1)
    except Exception:
        return None


class Trace:
    def __init__(self):
        self.steps = []

    def log(self, agent, kind, ms, detail, model=None, tokens=None):
        self.steps.append({"agent": agent, "kind": kind, "model": model or "—",
                           "ms": round(ms), "tokens": tokens, "detail": detail})


# ── Intent agent (LLM, with deterministic fallback) ──────────────────────────

ALIASES = {"giants": "oracle_park", "ballpark": "oracle_park", "warriors": "chase_center",
           "airport": "sfo", "wharf": "fishermans_wharf", "alamo square": "painted_ladies",
           "dolores": "dolores_park", "the mission": "mission_16th", "fidi": "montgomery",
           "financial district": "montgomery", "ggp": "golden_gate_park", "de young": "golden_gate_park"}


def alias_place(text):
    """Landmark key when the words contain one of our curated ALIASES as a whole word —
    local slang Claude can misread ("FiDi" isn't the Ferry Building). Addresses don't count."""
    t = text.lower()
    if re.search(r"\d", t):
        return None
    for alias, key in ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return key
    return None


def match_place(text):
    t = text.lower().strip(" .,!?")
    for alias, key in ALIASES.items():
        if alias in t:
            return key
    if re.search(r"\d", t):          # "500 Folsom St" is an address — geocode it, don't guess a landmark
        return None
    names = {PLACES[k][0].lower(): k for k in geo.landmarks()}
    names.update({k.replace("_", " "): k for k in geo.landmarks()})
    hit = difflib.get_close_matches(t, list(names), n=1, cutoff=0.45)
    if hit:
        return names[hit[0]]
    for n, key in names.items():                      # substring fallback ("coit" → coit tower)
        if t and (t in n or any(w in n.split() for w in t.split() if len(w) > 3)):
            return key
    return None


def parse_intent_rules(query, sf_context=True):
    out = {}
    q = query.lower()
    m = re.search(r"from (.+?) to (.+?)(?:\s+(?:by|at|before|under|and|,|i |—|-)\s|[,.!?]|$)", q)
    if not m:
        m = re.search(r"^(.+?) to (.+?)(?:\s+(?:by|at|before|under|and)\s|[,.!?]|$)", q)
    if m:
        # Outside SF, never fuzzy-match onto SF landmarks ("King's Cross" ≠ "Van Ness") — geocode instead.
        if sf_context:
            out["origin"], out["destination"] = match_place(m.group(1)), match_place(m.group(2))
        out["origin_text"], out["destination_text"] = m.group(1).strip(), m.group(2).strip()
    elif " to " not in q:
        dest = re.search(r"(?:get me to|take me to|going to|go to)\s+(.+?)(?:\s+(?:by|at|under)\s|[,.!?]|$)", q)
        if dest:
            if sf_context:
                out["destination"] = match_place(dest.group(1))
            out["destination_text"] = dest.group(1).strip()
    t = re.search(r"(?:by|at|before)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", q)
    if t:
        h = int(t.group(1)) % 12 + (12 if (t.group(3) == "pm" or (not t.group(3) and int(t.group(1)) < 8)) else 0)
        out["hour"] = h
    b = re.search(r"under \$?(\d+)", q)
    if b:
        out["max_cost"] = float(b.group(1))
    w = dict(DEFAULTS["weights"])
    if re.search(r"cheap|budget|save money|broke", q):
        w["cost"] = 3.0
    if re.search(r"steps|healthy|exercise|workout|calorie|walk more|active", q):
        w["health"] = 3.0
    if re.search(r"fast|quick|hurry|late|asap", q):
        w["time"] = 3.0
    if w != DEFAULTS["weights"]:
        out["weights"] = w
    if re.search(r"rain|raining|wet", q):
        out["weather"] = "rain"
    if re.search(r"game|giants|warriors|concert", q):
        out["event"] = True
    if re.search(r"no hills|avoid hills|flat", q):
        out["avoid_steep"] = True
    for mode, pattern in (("barcrawl", r"\bbars?\b|drinks|crawl|bar hop|pub crawl|night out"),
                          ("burn", r"workout|exercise|steps|burn|calorie"),
                          ("broke", r"cheap|budget|broke|save money"),
                          ("hustle", r"fast|quick|hurry|late|asap")):
        if re.search(pattern, q):
            out["mode"] = mode
            break
    return {k: v for k, v in out.items() if v is not None}


INTENT_TOOL = {
    "name": "trip_request",
    "description": "Structured trip request extracted from the rider's message. Only fill "
                   "fields the rider actually stated or clearly implied; use null otherwise.",
    "input_schema": {
        "type": "object",
        "properties": {
            "origin": {"type": ["string", "null"], "enum": list(PLACES) + [None]},
            "destination": {"type": ["string", "null"], "enum": list(PLACES) + [None]},
            "origin_text": {"type": ["string", "null"],
                            "description": "The rider's own words for the start if it is NOT a catalog landmark (e.g. a street address)"},
            "destination_text": {"type": ["string", "null"],
                                 "description": "The rider's own words for the destination if it is NOT a catalog landmark"},
            "hour": {"type": ["integer", "null"], "description": "Departure/arrival hour 0-23"},
            "max_cost": {"type": ["number", "null"], "description": "Budget in USD"},
            "weather": {"type": ["string", "null"], "enum": ["clear", "rain", "fog", None]},
            "event": {"type": ["boolean", "null"],
                      "description": "Giants/Warriors game or big event nearby"},
            "avoid_steep": {"type": ["boolean", "null"]},
            "mode": {"type": ["string", "null"],
                     "enum": ["hustle", "broke", "burn", "barcrawl", None],
                     "description": "hustle = fastest / late; broke = cheapest; burn = part "
                                    "transit, part workout; barcrawl = visit bars / night out. "
                                    "Null if the rider gave no hint."},
            "weights": {"type": ["object", "null"],
                        "description": "Relative 0-3 importance of time, cost, health",
                        "properties": {"time": {"type": "number"}, "cost": {"type": "number"},
                                       "health": {"type": "number"}}},
        },
        "required": ["origin", "destination"],
    },
}


def intent_agent(query, trace, client, sf_context=True):
    t0 = time.perf_counter()
    rules = parse_intent_rules(query, sf_context)
    if client is None:
        trace.log("Intent", "rules", (time.perf_counter() - t0) * 1000,
                  f"offline parser → {json.dumps(rules)}")
        return rules
    catalog = "\n".join(f"{k}: {PLACES[k][0]}" for k in geo.landmarks())
    try:
        resp = client.messages.create(
            model=INTENT_MODEL, max_tokens=400,
            system="You turn city trip requests (any city worldwide) into structured data. The "
                   "catalog below lists San Francisco landmarks only: use a catalog key only when the "
                   "rider clearly means that SF landmark. For any other place — a street address, a "
                   "landmark in another city, a station — leave the key null and copy the rider's "
                   "words (including the city if they gave one) into origin_text / destination_text "
                   "so it can be geocoded. Catalog:\n" + catalog,
            tools=[INTENT_TOOL], tool_choice={"type": "tool", "name": "trip_request"},
            messages=[{"role": "user", "content": query}])
        parsed = next(b.input for b in resp.content if b.type == "tool_use")
        parsed = {k: v for k, v in parsed.items() if v is not None and
                  (k not in ("origin", "destination") or v in PLACES)}
        merged = {**rules, **parsed}
        # A curated alias the rider actually typed beats Claude's guess for that endpoint.
        kept = []
        for k in ("origin", "destination"):
            text = rules.get(f"{k}_text")
            if text and rules.get(k) and alias_place(text) == rules[k] and parsed.get(k) != rules[k]:
                merged[k] = rules[k]
                kept.append(f"{k}={rules[k]} (alias, not {parsed.get(k) or parsed.get(f'{k}_text')})")
        trace.log("Intent", "llm", (time.perf_counter() - t0) * 1000,
                  f"{json.dumps(parsed)}" + (f"; kept {', '.join(kept)}" if kept else ""), INTENT_MODEL,
                  resp.usage.input_tokens + resp.usage.output_tokens)
        return merged
    except Exception as e:
        trace.log("Intent", "fallback", (time.perf_counter() - t0) * 1000,
                  f"LLM failed ({type(e).__name__}); rules → {json.dumps(rules)}")
        return rules


# ── Specialists (deterministic tool agents, run in parallel) ─────────────────

def _towards(origin, dest, cands, max_mi):
    """Places within max_mi of origin that are closer to dest than origin is."""
    base = tools.haversine_mi(origin, dest)
    return [c for c in tools.nearest(origin, cands, max_mi)
            if c not in (origin, dest) and tools.haversine_mi(c, dest) < base]


def walk_specialist(req):
    return [tools.Trip([tools.walk_leg(req["origin"], req["destination"], req["weight_kg"])],
                       "Walk & Terrain")]


def ride_specialist(req):
    o, d, h, ev, kg = req["origin"], req["destination"], req["hour"], req["event"], req["weight_kg"]
    trips = [tools.Trip([tools.ride_leg(o, d, h, ev)], "Ride-hail")]
    pickups = _towards(o, d, geo.landmarks(), 0.8)[:4]       # walk ahead: shorter ride
    if req.get("region") == "world":                         # no landmark list abroad: sample the walk
        try:
            pickups = world.pickup_points_along(o, d)
        except FeedError:
            pickups = []
    if tools.surge_at(o, h, ev)[0] > 1:             # walk out of the surge zone, any direction
        reach = req["max_walk_leg_mi"] / tools.WALK_CIRCUITY
        escapes = [p for p in tools.nearest(o, geo.landmarks(), reach)
                   if p not in (o, d) and tools.surge_at(p, h, ev)[0] == 1]
        pickups = list(dict.fromkeys(escapes[:3] + pickups))
    o_surge = tools.surge_at(o, h, ev)[0]
    pickups = [p for p in pickups if tools.surge_at(p, h, ev)[0] <= o_surge]  # never walk into surge
    dropoffs = _towards(d, o, geo.landmarks(), 0.6)[:3]      # hop out early and walk the rest
    for p in pickups:
        trips.append(tools.Trip([tools.walk_leg(o, p, kg), tools.ride_leg(p, d, h, ev)], "Ride-hail"))
    for q in dropoffs:
        trips.append(tools.Trip([tools.ride_leg(o, q, h, ev), tools.walk_leg(q, d, kg)], "Ride-hail"))
    for p in pickups[:2]:
        for q in dropoffs[:2]:
            if p != q:
                trips.append(tools.Trip([tools.walk_leg(o, p, kg), tools.ride_leg(p, q, h, ev),
                                         tools.walk_leg(q, d, kg)], "Ride-hail"))
    return trips


def transit_specialist(req):
    o, d, h, ev, kg = req["origin"], req["destination"], req["hour"], req["event"], req["weight_kg"]
    trips = []
    base = tools.haversine_mi(o, d)
    reach = req["max_walk_leg_mi"] / tools.WALK_CIRCUITY      # straight-line walking reach
    for line in TRANSIT_LINES:
        # Don't walk away from the destination just to catch a train.
        toward = [s for s in line["stops"] if tools.haversine_mi(s, d) <= base + 0.15]
        boards = [s for s in tools.nearest(o, toward, 1.2)][:2]
        alights = tools.nearest(d, line["stops"], 2.5)[:2]
        # Burn-style hybrids: walk to a stop farther along, or hop off early and walk in.
        boards += [s for s in tools.nearest(o, toward, reach)
                   if s not in boards and tools.haversine_mi(o, s) >= 0.4][-2:]
        alights += [s for s in tools.nearest(d, line["stops"], reach)
                    if s not in alights and tools.haversine_mi(s, d) >= 0.4
                    and tools.haversine_mi(s, d) < base][:2]
        for b in boards:
            for a in alights:
                if a == b or tools.haversine_mi(a, d) >= tools.haversine_mi(b, d):
                    continue
                legs = ([tools.walk_leg(o, b, kg)] if b != o else []) + \
                    [tools.transit_leg(line, b, a)]
                if a != d:
                    walk_out = tools.walk_leg(a, d, kg)
                    if walk_out.distance_mi <= req["max_walk_leg_mi"]:
                        trips.append(tools.Trip(legs + [walk_out], "Transit"))
                    trips.append(tools.Trip(legs + [tools.ride_leg(a, d, h, ev)], "Transit"))
                else:
                    trips.append(tools.Trip(legs, "Transit"))
    return trips


def dock_status(key, req):
    """Live GBFS availability when the trip leaves this hour; deterministic fallback otherwise."""
    if req.get("live_now"):
        try:
            lat, lon = tools.latlon(key)
            live = bikes.status_near(lat, lon)
            if live:
                req["_bike_source"] = "GBFS live"
                return live
        except FeedError:
            pass
    req.setdefault("_bike_source", "simulated (future hour or feed down)")
    return tools.dock_status(key, req["hour"])


def micromobility_specialist(req):
    o, d, h, kg = req["origin"], req["destination"], req["hour"], req["weight_kg"]
    trips = []
    starts = [k for k in tools.nearest(o, BIKE_DOCKS, 0.7) if k != d]
    ends = [k for k in tools.nearest(d, BIKE_DOCKS, 0.7) if dock_status(k, req)["open_docks"] > 0]
    for s in starts[:2]:
        status = dock_status(s, req)
        for e in ends[:2]:
            if s == e:
                continue
            for ebike in (False, True):
                if (status["ebike"] if ebike else status["classic"]) == 0:
                    continue
                ride = tools.bike_leg(s, e, ebike, h, kg)
                count = status["ebike"] if ebike else status["classic"]
                where = f" at {status['station']}" if status.get("station") else ""
                noun = ("e-bike" if ebike else "bike") + ("" if count == 1 else "s")
                ride.note = f"{count} {noun} available{where}" + \
                    (" (GBFS live)" if status.get("source") else " (simulated)")
                legs = ([tools.walk_leg(o, s, kg)] if s != o else []) + [ride] + \
                    ([tools.walk_leg(e, d, kg)] if e != d else [])
                trips.append(tools.Trip(legs, "Micromobility"))
    return trips


def world_transit_specialist(req):
    """Any city: Transitous itineraries (walk + metro/bus/tram/rail/ferry, real-time where published)."""
    try:
        return world.transit_trips(req["origin"], req["destination"], req["weight_kg"],
                                   req["depart_at"], req["live_now"])
    except FeedError as e:
        req["_world_transit"] = f"unavailable ({e})"
        return []


def world_bikes_specialist(req):
    """Any city with a bike-share network listed on CityBikes."""
    try:
        trips, network = world.bike_trips(req["origin"], req["destination"], req["hour"], req["weight_kg"])
        req["_bike_source"] = f"CityBikes live ({network})" if network else "no bike share nearby"
        return trips
    except FeedError:
        req["_bike_source"] = "CityBikes unavailable"
        return []


SF_SPECIALISTS = {"Walk & Terrain": walk_specialist, "Ride-hail": ride_specialist,
                  "Transit": transit_specialist, "Micromobility": micromobility_specialist}
WORLD_SPECIALISTS = {"Walk & Terrain": walk_specialist, "Ride-hail": ride_specialist,
                     "Transit (Transitous)": world_transit_specialist,
                     "Micromobility (CityBikes)": world_bikes_specialist}
SPECIALISTS = SF_SPECIALISTS     # kept for callers that predate worldwide support


# ── Context, Health, Critic, Ranker ──────────────────────────────────────────

def context_agent(req, trace):
    t0 = time.perf_counter()
    notes = []
    req["weather_detail"] = None
    if req["weather"] == "live":
        lat, lon = tools.latlon(req["origin"])
        # NWS for US trips (more local), Open-Meteo everywhere else and as the fallback.
        sources = ([("NWS", weather.at)] if geo.in_us(lat, lon) else []) + [("Open-Meteo", world.weather_at)]
        for label, fetch in sources:
            try:
                w = fetch(lat, lon, req["hour"])
                req["weather"], req["weather_detail"] = w["condition"], w
                notes.append(f"{label} {hour_label(req['hour'])}: {w['summary']}, {w['temp_f']}°F, "
                             f"wind {w['wind_mph']} mph, rain {w['precip_pct']}% [{w['cache']}]")
                break
            except (FeedError, KeyError, IndexError, TypeError, ValueError) as e:
                notes.append(f"{label} unavailable ({type(e).__name__})")
        else:
            req["weather"] = "clear"
            notes.append("no live weather → assuming clear")
    if (req["weather_detail"] or {}).get("wind_mph", 0) > 20:
        req["no_bikes"] = True
        notes.append("wind > 20 mph → bikes off")
    if req["weather"] == "rain":
        req["max_walk_leg_mi"] = min(req["max_walk_leg_mi"], 0.5)
        req["max_total_walk_mi"] = min(req["max_total_walk_mi"], 0.8)
        notes.append("rain → walk limits tightened to 0.5 mi/leg, 0.8 mi total; bikes off")
    if req["hour"] >= 21 or req["hour"] < 6:
        req["max_walk_leg_mi"] = min(req["max_walk_leg_mi"], 1.0)
        notes.append("after dark → walk legs capped at 1.0 mi")
    if req["event"]:
        notes.append("event → stadium-area ride surge active 5–11 pm")
    trace.log("Context", "rules", (time.perf_counter() - t0) * 1000,
              "; ".join(notes) or "clear daytime — no adjustments")
    return req


def hour_label(h):
    return "12 am" if h == 0 else f"{h} am" if h < 12 else "12 pm" if h == 12 else f"{h - 12} pm"


def realtime_agent(trips, req, trace):
    """511 live arrivals replace schedule waits; 511 alerts flag affected trips."""
    t0 = time.perf_counter()
    if req.get("region") == "world":
        trace.log("Realtime", "rules", 0, "outside SF: live times come from Transitous where agencies publish them")
        return "Transitous (live where published)"
    if not five11.enabled():
        trace.log("Realtime (511)", "fallback", 0,
                  "no FIVE11_API_KEY → schedule headways (get a free key at 511.org/open-data/token)")
        return "schedule (no 511 key)"
    if not req.get("live_now"):
        trace.log("Realtime (511)", "rules", 0, "trip isn't leaving this hour → schedule headways")
        return "schedule (future hour)"
    # Fastest trips first, so the few lookups we can afford go where they matter.
    keyed = {}
    for t in sorted(trips, key=lambda t: t.total_min):
        for l in t.legs:
            if l.mode in ("muni", "cable", "bart"):
                keyed.setdefault((l.mode, l.line_id, l.frm, l.to), []).append(l)
    hits, misses = 0, 0
    for (mode, line_id, frm, to), legs in list(keyed.items())[:MAX_REALTIME_LOOKUPS]:
        arr = five11.next_arrival(mode, line_id, tools.latlon(frm), tools.latlon(to))
        if not arr:
            misses += 1
            continue
        hits += 1
        for l in legs:
            l.wait_min = arr["wait_min"]
            l.source = "511.StopMonitoring"
            l.note = (f"next in {arr['wait_min']:.0f} min at {arr['stop']}"
                      f"{' (live)' if arr['realtime'] else ' (scheduled)'}")
    flagged = 0
    for mode in {l.mode for t in trips for l in t.legs if l.mode in ("muni", "cable", "bart")}:
        by_route = five11.alerts(mode)
        for t in trips:
            for l in t.legs:
                if l.mode == mode and by_route.get(l.line_id):
                    t.flags.append(f"⚠ {l.line}: {by_route[l.line_id][0][:70]}")
                    flagged += 1
    st = five11.status()
    trace.log("Realtime (511)", "tools", (time.perf_counter() - t0) * 1000,
              f"{hits} live arrivals, {misses} without prediction, {flagged} alert flags; "
              f"511 calls this hour {st['calls_last_hour']}/{st['budget']}")
    return "511 live" if hits else "schedule (511 had no predictions)"


def _street_leg(l, req):
    """Rebuild a walk / bike / ride leg from its real OSRM street route."""
    r = osrm.route(l.mode, tools.latlon(l.frm), tools.latlon(l.to))
    if l.mode == "walk":
        new = tools.walk_leg(l.frm, l.to, req["weight_kg"], dist=r["distance_mi"],
                             path=r["path"], source=f"{r['engine']}.foot")
    elif l.mode in ("bike", "ebike"):
        new = tools.bike_leg(l.frm, l.to, l.mode == "ebike", req["hour"], req["weight_kg"],
                             dist=r["distance_mi"], path=r["path"], source=f"{r['engine']}.bike")
    else:
        new = tools.ride_leg(l.frm, l.to, req["hour"], req["event"], dist=r["distance_mi"],
                             free_flow_min=r["duration_min"], path=r["path"],
                             source=f"{r['engine']}.car+traffic")
    new.note = l.note
    return new, r["cache"]


def routing_agent(trips, req, trace):
    """Swap estimated walk / bike / ride legs for real OSRM street routes, in place."""
    t0 = time.perf_counter()
    if osrm_off():
        trace.log("Routing (OSRM)", "fallback", 0, "offline → straight-line estimates")
        return "estimated (offline)"
    todo = {}
    for t in sorted(trips, key=lambda t: t.total_min):
        for l in t.legs:
            if l.mode in osrm.PROFILE and not l.source.startswith(("osrm", "ors")):
                todo.setdefault((l.mode, l.frm, l.to), l)
    keys = list(todo)[:MAX_ROUTED_LEGS]
    routed, caches, failed = {}, {"live": 0, "memory": 0, "disk": 0}, 0
    # 2 at a time is polite to the shared OSRM server; legs still pending when the time
    # budget runs out keep their estimates (they're usually cached by the next plan).
    pool = ThreadPoolExecutor(max_workers=2)
    futures = {k: pool.submit(_street_leg, todo[k], req) for k in keys}
    done, _ = wait(futures.values(), timeout=ROUTING_BUDGET_S)
    pool.shutdown(wait=False, cancel_futures=True)
    for k, f in futures.items():
        if f not in done:
            continue
        try:
            routed[k], cache = f.result()
            caches[cache] = caches.get(cache, 0) + 1
        except FeedError:
            failed += 1
    timed_out = sum(1 for f in futures.values() if f not in done)
    for t in trips:
        t.legs = [routed.get((l.mode, l.frm, l.to), l) for l in t.legs]
    skipped = len(todo) - len(keys)
    trace.log("Routing (OSRM)", "tools", (time.perf_counter() - t0) * 1000,
              f"{len(routed)} street legs routed ({caches['live']} live, "
              f"{caches['memory'] + caches['disk']} cached), {failed} failed"
              + (f", {timed_out} past the {ROUTING_BUDGET_S:.0f}s budget" if timed_out else "")
              + (f", {skipped} over cap kept as estimates" if skipped else ""))
    if not routed:
        return "estimated (street routing unavailable)"
    engines = " + ".join(sorted({"OpenRouteService" if l.source.startswith("ors") else "OSRM" for l in routed.values()}))
    return f"Street routes ({engines})" + ("" if not (failed or skipped or timed_out) else ", partial")


def osrm_off():
    return os.environ.get("HOPPER_OFFLINE") == "1" or os.environ.get("HOPPER_NO_OSRM") == "1"


def health_agent(trips, req, trace):
    t0 = time.perf_counter()
    for t in trips:
        if t.climb_ft >= 150:
            t.flags.append(f"⛰ {t.climb_ft} ft climb")
        if t.steps:
            t.flags.append(f"{round(100 * t.steps / req['step_goal'])}% of step goal")
    trace.log("Health", "tools", (time.perf_counter() - t0) * 1000,
              f"scored {len(trips)} trips (ACSM walking eq., MET cycling, Tobler hill speed)")


def critic_agent(trips, req, trace):
    t0 = time.perf_counter()
    ok, rejected = [], []
    walk_only = tools.walk_leg(req["origin"], req["destination"], req["weight_kg"])
    for t in trips:
        reasons = tools.validate_trip(t, req)
        # A paid trip slower than just walking there is a pointless detour, not an option.
        if t.cost > 0 and walk_only.distance_mi <= 3 and t.total_min > walk_only.minutes:
            reasons.append(f"slower than walking the whole way ({walk_only.minutes:.0f} min)")
        if req["weather"] == "rain" and any(l.mode in ("bike", "ebike") for l in t.legs):
            reasons.append("bike share disabled in rain")
        if req.get("no_bikes") and any(l.mode in ("bike", "ebike") for l in t.legs):
            reasons.append("bike share disabled in high wind")
        (rejected if reasons else ok).append((t, reasons))
    trace.log("Critic", "tools", (time.perf_counter() - t0) * 1000,
              f"{len(ok)} feasible, {len(rejected)} rejected")
    return [t for t, _ in ok], [{"trip": " → ".join(f"{l.mode}" for l in t.legs) +
                                 f" via {tools.name(t.legs[0].to)}", "reasons": r}
                                for t, r in rejected]


def is_walk_ride(trip):
    return {l.mode for l in trip.legs} == {"walk", "ride"}


def ranker_agent(trips, weights, trace, mode=None, caps=None):
    t0 = time.perf_counter()
    trips, notice = modes.mode_filter(trips, mode, caps)
    if mode in modes.TRIP_MODES:
        weights = modes.MODES[mode]["weights"]
    picks, front, scores = tools.pick_options(trips, weights)
    if mode in modes.TRIP_MODES:
        best = f"Best for {modes.MODES[mode]['label']}"
        picks[0] = (picks[0][0], picks[0][1].replace("Recommended", best))
    for t, _ in picks:
        if mode == "burn":
            t.flags = [f for f in t.flags if not f.startswith("🔥")] + [
                f"🔥 {round(100 * modes.active_share(t))}% active"]
    # Hopper's signature combo: always show the best walk + ride trip, even when bikes
    # or transit push it off the Pareto frontier — it's the option riders came for.
    note = ""
    if not any(is_walk_ride(t) for t, _ in picks):
        # Sanity bound: a walk + ride should add at most ~15 min over riding door to door,
        # otherwise it's a scenic detour, not a commute option.
        rides = [t.total_min for t in trips if {l.mode for l in t.legs} == {"ride"}]
        bound = (min(rides) if rides else min(t.total_min for t in trips)) + 15
        combos = [t for t in trips if is_walk_ride(t) and t.total_min <= bound]
        if combos:
            all_scores = tools.score_trips(trips, weights)
            best = min(combos, key=lambda t: all_scores[t.id])
            picks.append((best, "Walk + Ride"))
            scores = {**scores, best.id: all_scores[best.id]}
            note = "; added best Walk + Ride combo"
    trace.log("Ranker", "tools", (time.perf_counter() - t0) * 1000,
              f"mode {mode or 'custom'}: {len(front)} on Pareto frontier of {len(trips)}; "
              f"weights {weights}{note}" + (f"; {notice}" if notice else ""))
    return picks, front, scores, notice


# ── Explainer (LLM, with template fallback) ──────────────────────────────────

def _leg_phrase(l):
    verb = {"walk": "Walk", "ride": "Ride", "bike": "Bike", "ebike": "E-bike"}.get(l.mode)
    if verb:
        return f"{verb} {l.distance_mi} mi to {tools.name(l.to)}"
    return f"{l.line} to {tools.name(l.to)}"


def trade_offs(trip, baseline):
    """Pre-computed deltas vs. the door-to-door ride, so no agent ever does arithmetic."""
    parts = []
    dc, dt, dk = round(baseline.cost - trip.cost, 2), round(trip.total_min - baseline.total_min), \
        trip.kcal - baseline.kcal
    if dc > 0.5:
        parts.append(f"saves ${dc:.2f}")
    elif dc < -0.5:
        parts.append(f"costs ${-dc:.2f} more")
    if dt > 0:
        parts.append(f"+{dt} min")
    elif dt < 0:
        parts.append(f"{-dt} min faster")
    if dk > 10:
        parts.append(f"+{dk} kcal")
    return parts


def template_explanation(trip, baseline):
    parts = trade_offs(trip, baseline)
    route = "; ".join(_leg_phrase(l) for l in trip.legs)
    if not parts:
        return f"{route}. The door-to-door baseline — fastest, no exercise."
    return f"{route}. {', '.join(parts)} vs. a door-to-door ride."


NUM = re.compile(r"\d+(?:\.\d+)?")


def grounded(sentence, facts_blob):
    """True if every number in the sentence appears in the facts we gave the model.
    Compared as values, so "3.00" matches 3.0 but "40" never matches 4."""
    allowed = {float(n) for n in NUM.findall(facts_blob)}
    return all(float(n) in allowed for n in NUM.findall(sentence))


def explainer_agent(picks, baseline, trace, client):
    t0 = time.perf_counter()
    fallback = {t.id: template_explanation(t, baseline) for t, _ in picks}
    if client is None:
        trace.log("Explainer", "template", (time.perf_counter() - t0) * 1000, "offline template")
        return fallback
    payload = [{"id": t.id, "label": lbl, "minutes": round(t.total_min), "cost": f"${t.cost:.2f}",
                "kcal": t.kcal, "legs": [_leg_phrase(l) for l in t.legs],
                "trade_offs_vs_ride": trade_offs(t, baseline) or ["this IS the door-to-door ride"],
                "flags": t.flags} for t, lbl in picks]
    try:
        resp = client.messages.create(
            model=EXPLAIN_MODEL, max_tokens=500,
            system="You write the one-line pitch for each commute option in a San Francisco trip "
                   "app. For each option write ONE plain, grammatical sentence of at most 20 words "
                   "that says why a rider would pick it. Lead with the route idea (e.g. 'Walk to "
                   "Caltrain, then ride'), then quote the trade-offs exactly as given in "
                   "trade_offs_vs_ride. Copy numbers verbatim; never compute, round, or invent "
                   "numbers. Don't repeat the label.",
            tools=[{"name": "explanations", "description": "One sentence per option id.",
                    "input_schema": {"type": "object", "properties": {"items": {
                        "type": "array", "items": {"type": "object", "properties": {
                            "id": {"type": "string"}, "why": {"type": "string"}},
                            "required": ["id", "why"]}}}, "required": ["items"]}}],
            tool_choice={"type": "tool", "name": "explanations"},
            messages=[{"role": "user", "content": json.dumps({"options": payload}, ensure_ascii=False)}])
        items = next(b.input for b in resp.content if b.type == "tool_use")["items"]
        facts = {p["id"]: json.dumps(p, ensure_ascii=False) for p in payload}   # "渋８８" stays checkable
        out, dropped = dict(fallback), 0
        for i in items:
            if i.get("id") in fallback:
                if grounded(i["why"], facts[i["id"]]) and len(i["why"].split()) <= 28:
                    out[i["id"]] = i["why"]
                else:
                    dropped += 1          # invented a number or rambled → keep the template
        for t, lbl in picks:              # the card already shows the label as a chip
            out[t.id] = re.sub(rf"^{re.escape(lbl)}\s*:\s*", "", out[t.id])
        trace.log("Explainer", "llm", (time.perf_counter() - t0) * 1000,
                  f"{len(items) - dropped} explanations"
                  + (f", {dropped} failed the number check → template" if dropped else ""),
                  EXPLAIN_MODEL,
                  resp.usage.input_tokens + resp.usage.output_tokens)
        return out
    except Exception as e:
        trace.log("Explainer", "fallback", (time.perf_counter() - t0) * 1000,
                  f"LLM failed ({type(e).__name__}); template used")
        return fallback


# ── Orchestrator ─────────────────────────────────────────────────────────────

class PlanError(ValueError):
    pass


def orchestrate(body):
    """Full swarm run. Returns the response dict plus the raw trips for re-ranking."""
    trace = Trace()
    client = None if body.get("_quick") else _llm()     # ground legs for flights skip Claude
    # Cost guard: a plan makes up to 2 Claude calls (Intent + Explainer). Past the daily
    # caps, fall back to rules + templates — every number stays identical.
    if client is not None and not guard.claude_allowed(body.get("_visitor") or "local", calls=2):
        client = None
        trace.log("Cost guard", "rules", 0, "daily Claude budget reached → rules + templates (same numbers)")
    t_start = time.perf_counter()

    req = {**DEFAULTS, **{k: v for k, v in body.items() if v not in (None, "") and k in DEFAULTS},
           "weights": {**DEFAULTS["weights"], **(body.get("weights") or {})}}
    try:
        # Form values may be landmark keys, geo keys, or {name, lat, lon} from address search.
        req["origin"] = geo.resolve(body.get("origin_place") or body.get("origin"))
        req["destination"] = geo.resolve(body.get("destination_place") or body.get("destination"))
    except ValueError as e:
        raise PlanError(str(e)) from None
    # Bias free-text geocoding toward where the rider is looking (map centre) or their pickup.
    near = None
    try:
        lat, lon = (float(x) for x in (body.get("near") or [])[:2])
        near = [lat, lon] if -85 <= lat <= 85 and -180 <= lon <= 180 else None
    except (TypeError, ValueError):
        pass
    if near is None and req.get("origin") in PLACES:
        near = tools.latlon(req["origin"])
    if (body.get("query") or "").strip():
        sf_context = near is None or world.in_sf_area(*near)
        parsed = intent_agent(body["query"], trace, client, sf_context)
        if not sf_context:     # SF landmark keys make no sense for a London or Tokyo request
            for k in ("origin", "destination"):
                if parsed.get(k) in PLACES and not geo.is_geo(parsed[k]) and parsed.get(f"{k}_text"):
                    parsed.pop(k)
        req.update({k: v for k, v in parsed.items() if k != "weights" and not k.endswith("_text")})
        if "weights" in parsed:
            req["weights"] = {**req["weights"], **parsed["weights"]}
        # Words that weren't a landmark ("500 Folsom St") get geocoded inside SF.
        for k in ("origin", "destination"):
            text = parsed.get(f"{k}_text")
            if text and k not in parsed:
                t0 = time.perf_counter()
                try:
                    key = geo.geocode_first(text, near=near)
                except ValueError:
                    key = None
                trace.log("Geocoder (Photon)", "tools", (time.perf_counter() - t0) * 1000,
                          f"'{text}' → {tools.name(key) if key else 'no SF match'}")
                if not key:
                    raise PlanError(f"Couldn't find “{text}” in San Francisco. Try a street address or a landmark.")
                req[k] = key
    if req["mode"] == "barcrawl":
        # Bar Crawl is a different planner with a 21+ gate — hand back to the UI.
        return {"redirect": "barcrawl", "start": req.get("origin"), "end": req.get("destination"),
                "hour": req["hour"], "trace": trace.steps}, None, None, None, None

    for k in ("origin", "destination"):
        if req.get(k) not in PLACES:
            raise PlanError(f"Couldn't figure out the {k}. Search for an address or pick a landmark.")
        geo.ensure_ready(req[k])
        if not tools.in_sf(req[k]):
            raise PlanError(f"{tools.name(req[k])} is outside San Francisco — SF only for now.")
    if req["origin"] == req["destination"]:
        raise PlanError("Origin and destination are the same place.")
    span = tools.haversine_mi(req["origin"], req["destination"])
    if span > 100:
        if body.get("_quick"):
            raise PlanError(f"Those places are {span:,.0f} miles apart.")
        # Too far for ground travel: hand off to the flight planner (door to door).
        return {"redirect": "flights", "miles": round(span),
                "origin": {"key": req["origin"], "name": tools.name(req["origin"]),
                           "lat": tools.latlon(req["origin"])[0], "lon": tools.latlon(req["origin"])[1]},
                "destination": {"key": req["destination"], "name": tools.name(req["destination"]),
                                "lat": tools.latlon(req["destination"])[0], "lon": tools.latlon(req["destination"])[1]},
                "trace": trace.steps}, None, None, None, None
    req["region"] = world.region(req["origin"], req["destination"])
    # Times are local to where the trip starts (SF, Paris, Tokyo…), not to the server.
    req["tz"] = world.timezone_at(*tools.latlon(req["origin"]))
    now_local = world.local_now(req["tz"])
    leave_now = req["hour"] in (None, "", "now") or int(req["hour"]) % 24 == now_local.hour
    req["hour"] = now_local.hour if leave_now else int(req["hour"]) % 24
    depart = now_local if leave_now else now_local.replace(hour=req["hour"], minute=0, second=0, microsecond=0)
    if not leave_now and depart < now_local:
        depart += timedelta(days=1)
    req["depart_at"], req["live_now"] = depart, leave_now   # live arrivals/docks only for "now"
    weather_input = req["weather"]

    req = context_agent(req, trace)

    t0 = time.perf_counter()
    specialists = WORLD_SPECIALISTS if req["region"] == "world" else SF_SPECIALISTS
    with ThreadPoolExecutor(max_workers=len(specialists)) as pool:
        futures = {n: pool.submit(fn, req) for n, fn in specialists.items()}
        results = {n: f.result() for n, f in futures.items()}
    fan_ms = (time.perf_counter() - t0) * 1000
    for n, trips in results.items():
        trace.log(n, "tools", fan_ms, f"{len(trips)} candidate trips (parallel fan-out)")

    seen, candidates = set(), []
    for trips in results.values():
        for t in trips:
            if t.signature not in seen:
                seen.add(t.signature)
                t.id = f"t{len(candidates)}"
                candidates.append(t)

    transit_source = realtime_agent(candidates, req, trace)
    # Pass 1 prunes on cheap estimates; only survivors (plus the door-to-door baseline)
    # get real OSRM street routes, then the Critic re-checks them on real distances.
    feasible, rejected = critic_agent(candidates, req, trace)
    baseline_trip = tools.Trip([tools.ride_leg(req["origin"], req["destination"],
                                               req["hour"], req["event"])], "baseline")
    routes_source = routing_agent(feasible + [baseline_trip], req, trace)
    health_agent(feasible, req, trace)
    feasible, rejected2 = critic_agent(feasible, req, trace)
    rejected += rejected2
    if not feasible:
        raise PlanError("No feasible trip under these limits — try relaxing walk distance or budget.")
    caps = {"max_walk_leg_mi": req["max_walk_leg_mi"], "max_total_walk_mi": req["max_total_walk_mi"]}
    picks, front, scores, notice = ranker_agent(feasible, req["weights"], trace, req["mode"], caps)
    why = explainer_agent(picks, baseline_trip, trace, client)

    options = [{**t.to_dict(), "label": lbl, "why": why[t.id], "score": round(scores[t.id], 3)}
               for t, lbl in picks]
    return {
        "request": {**{k: req[k] for k in ("origin", "destination", "hour", "event", "mode",
                                           "weights", "max_walk_leg_mi", "max_total_walk_mi",
                                           "avoid_steep", "max_cost", "weight_kg")},
                    "weather": weather_input, "tz": req["tz"], "leave_now": req["live_now"],
                    "region": req["region"]},
        "units": "mi" if req["tz"].startswith("America/") or req["tz"] in ("Europe/London", "Europe/Dublin") else "km",
        "notice": notice,
        "live": {"weather": req["weather_detail"], "condition": req["weather"],
                 "transit": transit_source, "routes": routes_source,
                 "bikes": req.get("_bike_source", "not used"),
                 "world_transit": req.get("_world_transit", "ok" if req["region"] == "world" else "not used"),
                 "five11": five11.status(), "live_now": req["live_now"]},
        "origin_name": tools.name(req["origin"]), "destination_name": tools.name(req["destination"]),
        "places": {k: {"key": req[k], "name": tools.name(req[k]), "lat": tools.latlon(req[k])[0],
                       "lon": tools.latlon(req[k])[1]} for k in ("origin", "destination")},
        "options": options,
        "baseline": baseline_trip.to_dict(),
        "stats": {"candidates": len(candidates), "feasible": len(feasible),
                  "frontier": len(front), "ms": round((time.perf_counter() - t_start) * 1000),
                  "llm": client is not None},
        "rejected": rejected[:12],
        "trace": trace.steps,
    }, feasible, why, baseline_trip, caps


def rerank(feasible, weights, why_cache, baseline_trip, mode=None, caps=None):
    """Mode switches and slider moves re-run only the Ranker — no specialists, no LLM calls."""
    trace = Trace()
    picks, _, scores, notice = ranker_agent(feasible, weights, trace, mode, caps)
    options = [{**t.to_dict(), "label": lbl, "score": round(scores[t.id], 3),
                "why": why_cache.get(t.id) or template_explanation(t, baseline_trip)}
               for t, lbl in picks]
    return options, trace.steps, notice
