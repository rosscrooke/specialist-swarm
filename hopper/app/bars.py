"""🍸 Bar Crawl planner on OpenStreetMap bar data.

Bars come from the Overpass API (all named bars / pubs / beer gardens in SF in one query,
cached on disk for 7 days), falling back to the bundled snapshot in fixtures/sf_bars.json.
OpenStreetMap has no ratings, so the "cool score" is built from transparent signals —
notability (a Wikipedia/Wikidata entry), how thoroughly the bar is mapped, website /
Instagram / hours present, outdoor seating — plus a vibe match. The UI says so.

Rules: 21+ gate (enforced by the API), walking only between bars, the trip home is a
ride (simulated fare), no bikes or driving after the first stop.
"""
import json
import os
import re
import threading
import time
from pathlib import Path

from . import osrm, tools
from .live import FeedError, get_json

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = ('[out:json][timeout:60];nwr["amenity"~"^(bar|pub|biergarten)$"]["name"]'
         '(37.70,-122.52,37.835,-122.35);out center tags;')
SNAPSHOT = Path(__file__).parent / "fixtures" / "sf_bars.json"
KEEP = ("opening_hours", "website", "contact:instagram", "cocktails", "drink:beer", "drink:wine",
        "microbrewery", "brewery", "live_music", "lgbtq", "sport", "wikidata", "wikipedia",
        "outdoor_seating", "food", "cuisine", "description", "addr:housenumber", "addr:street",
        "min_age", "access")

VIBES = {
    "any": "Any vibe",
    "cocktail": "Cocktails",
    "brewery": "Craft beer",
    "dive": "Dive / saloon",
    "wine": "Wine",
    "live_music": "Live music",
    "sports": "Sports",
    "lgbtq": "LGBTQ+",
    "landmark": "Landmarks",
}
WALK_PENALTY_PER_MI = 2.0      # score points traded per mile walked between bars


def _compact(elements):
    bars = []
    for e in elements:
        t = e.get("tags", {})
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if not lat or not t.get("name") or t.get("access") in ("private", "members", "no") \
                or "yacht club" in t["name"].lower():
            continue
        bars.append({"id": f"{e['type'][0]}{e['id']}", "name": t["name"], "type": t.get("amenity"),
                     "lat": round(lat, 6), "lon": round(lon, 6), "n_tags": len(t),
                     "tags": {k: t[k] for k in KEEP if k in t}})
    return bars


_refresh_lock = threading.Lock()
_refresh_after = 0.0          # earliest time to try Overpass again after a failure


def _refresh_in_background():
    """Fetch fresh bars from Overpass without blocking a rider; back off 15 min on failure."""
    global _refresh_after
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        get_json(OVERPASS, {"data": QUERY}, ttl=604800, disk_ttl=604800, timeout=60)
    except FeedError:
        _refresh_after = time.time() + 900
    finally:
        _refresh_lock.release()


def load_bars():
    """(bars, source label). Cached live data if we have it; otherwise the bundled snapshot
    right away, with an Overpass refresh started in the background (it's often busy)."""
    try:
        data, meta = get_json(OVERPASS, {"data": QUERY}, ttl=604800, disk_ttl=604800, cache_only=True)
        bars = _compact(data.get("elements", []))
        if bars:
            return bars, f"OpenStreetMap live ({meta['cache']})"
    except FeedError:
        if time.time() >= _refresh_after and not os.environ.get("HOPPER_OFFLINE"):
            threading.Thread(target=_refresh_in_background, daemon=True).start()
    snap = json.loads(SNAPSHOT.read_text())
    return snap["bars"], f"OpenStreetMap snapshot {snap.get('snapshot', '')[:10]}"


def vibe_match(bar, vibe):
    t, name = bar["tags"], bar["name"].lower()
    if vibe in (None, "", "any"):
        return True
    if vibe == "cocktail":
        return t.get("cocktails") in ("yes", "only") or bool(re.search(r"cocktail|lounge|tiki", name))
    if vibe == "brewery":
        return t.get("microbrewery") == "yes" or "brewery" in t or bar["type"] == "biergarten" \
            or bool(re.search(r"brew|taproom|tap room|beer", name))
    if vibe == "dive":
        return bar["type"] == "pub" or bool(re.search(r"saloon|tavern|dive|inn\b", name))
    if vibe == "wine":
        return t.get("drink:wine") in ("yes", "served") or "wine" in name
    if vibe == "live_music":
        return t.get("live_music") == "yes"
    if vibe == "sports":
        return "sport" in t or "sports" in name
    if vibe == "lgbtq":
        return t.get("lgbtq") in ("primary", "friendly", "welcome")
    if vibe == "landmark":
        return "wikidata" in t or "wikipedia" in t
    return True


def cool_score(bar, vibe="any"):
    """Deterministic 'cool score' from OSM signals (no ratings exist in OSM)."""
    t = bar["tags"]
    s = 1.0
    s += 3.0 if ("wikidata" in t or "wikipedia" in t) else 0
    s += min(bar.get("n_tags", 0), 15) * 0.1
    s += 0.5 if "website" in t else 0
    s += 0.3 if "contact:instagram" in t else 0
    s += 0.5 if "opening_hours" in t else 0
    s += 0.4 if t.get("outdoor_seating") == "yes" else 0
    s += 2.0 if vibe not in (None, "", "any") and vibe_match(bar, vibe) else 0
    return round(s, 2)


def why_cool(bar):
    t, bits = bar["tags"], []
    if "wikidata" in t or "wikipedia" in t:
        bits.append("SF landmark (on Wikipedia)")
    if vibe_match(bar, "cocktail") and t.get("cocktails"):
        bits.append("cocktails")
    if vibe_match(bar, "brewery") and bar["type"] != "pub":
        bits.append("craft beer")
    if t.get("live_music") == "yes":
        bits.append("live music")
    if t.get("lgbtq") in ("primary", "friendly", "welcome"):
        bits.append("LGBTQ+")
    if "sport" in t:
        bits.append("sports on TV")
    if t.get("outdoor_seating") == "yes":
        bits.append("outdoor seating")
    if t.get("food") == "yes" or "cuisine" in t:
        bits.append("serves food")
    if t.get("description"):
        bits.append(t["description"][:80].rstrip("."))
    if not bits:
        return f"Neighborhood {bar['type']}."
    text = ", ".join(bits)
    return text[0].upper() + text[1:] + "."


def _pt(bar):
    return [bar["lat"], bar["lon"]]


def _greedy(first, pool, n, hop_mi, vibe):
    route, total = [first], cool_score(first, vibe)
    while len(route) < n:
        cur = route[-1]
        options = [(cool_score(b, vibe) - WALK_PENALTY_PER_MI * tools.haversine_pts(_pt(cur), _pt(b)), b)
                   for b in pool if b not in route and tools.haversine_pts(_pt(cur), _pt(b)) <= hop_mi]
        if not options:
            return None, 0
        gain, nxt = max(options, key=lambda x: x[0])
        route.append(nxt)
        total += gain
    return route, total


def choose_stops(bars, start, n, vibe, hop_mi, radius_mi=0.6):
    """Best and alternate N-bar routes near `start` ([lat, lon]). Pure; unit-tested."""
    near = [b for b in bars if tools.haversine_pts(start, _pt(b)) <= radius_mi]
    matching = [b for b in near if vibe_match(b, vibe)]
    pool = matching if len(matching) >= n else near
    firsts = sorted(pool, key=lambda b: -(cool_score(b, vibe)
                                          - WALK_PENALTY_PER_MI * tools.haversine_pts(start, _pt(b))))[:8]
    results = []
    for f in firsts:
        route, total = _greedy(f, pool, n, hop_mi, vibe)
        if route:
            total -= WALK_PENALTY_PER_MI * tools.haversine_pts(start, _pt(f))
            results.append((total, route))
    results.sort(key=lambda r: -r[0])
    if not results:
        return None, None
    best = results[0][1]
    alt = next((r for _, r in results[1:] if not set(b["id"] for b in r) & set(b["id"] for b in best)),
               results[1][1] if len(results) > 1 else None)
    return best, alt


def _routing_off():
    # Same switch the trip planner honours: offline / no-OSRM runs never touch OSRM or spend ORS budget.
    return os.environ.get("HOPPER_OFFLINE") == "1" or os.environ.get("HOPPER_NO_OSRM") == "1"


def _route(mode, a_pt, b_pt):
    if _routing_off():
        raise FeedError("street routing off")
    return osrm.route(mode, a_pt, b_pt)


def _walk(a_pt, b_pt, a_name, b_name, kg):
    try:
        r = _route("walk", a_pt, b_pt)
        dist, path, src = r["distance_mi"], r["path"], f"{r['engine']}.foot"
    except FeedError:
        dist, path, src = tools.haversine_pts(a_pt, b_pt) * tools.WALK_CIRCUITY, [a_pt, b_pt], "estimate"
    minutes = dist * tools.MI_TO_M / 1000 / tools.tobler_speed_kmh(0) * 60
    return {"mode": "walk", "frm_name": a_name, "to_name": b_name, "distance_mi": round(dist, 2),
            "minutes": round(minutes, 1), "wait_min": 0, "cost": 0.0,
            "kcal": round(tools.walk_kcal(dist * tools.MI_TO_M, minutes, 0, kg), 1),
            "steps": round(dist * tools.MI_TO_M / tools.STEP_LENGTH_M), "path": path, "source": src,
            "note": "", "surge": 1.0, "line": "", "grade": 0}


def _ride(a_pt, b_pt, a_name, b_name, hour, event):
    try:
        r = _route("ride", a_pt, b_pt)
        dist, path, src = r["distance_mi"], r["path"], f"{r['engine']}.car+traffic"
        minutes = r["duration_min"] * tools.traffic_factor(hour)
    except FeedError:
        dist = tools.haversine_pts(a_pt, b_pt) * tools.DRIVE_CIRCUITY
        path, src, minutes = [a_pt, b_pt], "estimate", tools.drive_minutes(dist, hour)
    mult, _ = tools.surge_at_point(a_pt, hour, event)
    return {"mode": "ride", "frm_name": a_name, "to_name": b_name, "distance_mi": round(dist, 2),
            "minutes": round(minutes, 1), "wait_min": tools.RIDE["pickup_wait_min"] + (3 if mult > 1 else 0),
            "cost": tools.ride_fare(dist, minutes, mult), "kcal": 0, "steps": 0, "path": path,
            "source": src, "note": "simulated fare — never drive after drinking", "surge": mult,
            "line": "", "grade": 0}


def clock(minutes_after_midnight):
    m = int(round(minutes_after_midnight)) % (24 * 60)
    h, mm = divmod(m, 60)
    return f"{(h % 12) or 12}:{mm:02d} {'am' if h < 12 else 'pm'}"


def build_itinerary(route, start_key, end_key, hour, minutes_per_stop, event, kg):
    start_pt, start_name = tools.latlon(start_key), tools.name(start_key)
    t = hour * 60
    walks, stops = [], []
    prev_pt, prev_name = start_pt, start_name
    for b in route:
        w = _walk(prev_pt, _pt(b), prev_name, b["name"], kg)
        walks.append(w)
        t += round(w["minutes"])     # whole minutes, so arrive → leave always reads as the stop length
        stops.append({"name": b["name"], "type": b["type"], "lat": b["lat"], "lon": b["lon"],
                      "arrive": clock(t), "leave": clock(t + minutes_per_stop),
                      "hours": b["tags"].get("opening_hours", "hours not listed — check before you go"),
                      "website": b["tags"].get("website", ""), "why": why_cool(b),
                      "cool_score": cool_score(b), "osm_id": b["id"]})
        t += minutes_per_stop
        prev_pt, prev_name = _pt(b), b["name"]
    ride_home = None
    if end_key:
        ride_home = _ride(prev_pt, tools.latlon(end_key), prev_name, tools.name(end_key),
                          int(t // 60) % 24, event)
    total_min = t - hour * 60
    notes = []
    if total_min > 120 and not any(b["tags"].get("food") == "yes" or "cuisine" in b["tags"] for b in route):
        notes.append("Crawl runs over 2 hours — grab food along the way.")
    if any("opening_hours" not in b["tags"] for b in route):
        notes.append("Some bars don't list hours in OpenStreetMap — check before you go.")
    return {"stops": stops, "walks": walks, "ride_home": ride_home,
            "totals": {"minutes": round(total_min), "walk_mi": round(sum(w["distance_mi"] for w in walks), 2),
                       "steps": sum(w["steps"] for w in walks), "kcal": round(sum(w["kcal"] for w in walks)),
                       "ride_home_cost": ride_home["cost"] if ride_home else 0.0,
                       "ends": clock(t)},
            "notes": notes}


def load_bars_near(lat, lon):
    """SF: bundled snapshot / cached citywide data. Elsewhere: live Overpass around the start."""
    from . import world
    if world.in_sf_area(lat, lon):
        return load_bars()
    try:
        elements, cache = world.bars_near(lat, lon, radius_m=1800)
    except FeedError as e:
        return [], f"unavailable ({e})"
    return _compact(elements), f"OpenStreetMap live ({cache})"


def plan_crawl(start_key, end_key, stops, vibe, hour, minutes_per_stop, weather_condition, event, kg):
    bars, source = load_bars_near(*tools.latlon(start_key))
    if not bars:
        return None, source
    hop_mi = 0.2 if weather_condition == "rain" else 0.4      # straight-line ≈ 0.25 / 0.5 mi walked
    best, alt = choose_stops(bars, tools.latlon(start_key), stops, vibe, hop_mi)
    if not best:
        best, alt = choose_stops(bars, tools.latlon(start_key), stops, vibe, hop_mi, radius_mi=1.0)
    if not best:
        return None, source
    out = {"itinerary": build_itinerary(best, start_key, end_key, hour, minutes_per_stop, event, kg),
           "alternate": [{"name": b["name"], "why": why_cool(b)} for b in alt] if alt else [],
           "bars_considered": len(bars), "source": source,
           "hop_limit_mi": round(hop_mi * tools.WALK_CIRCUITY, 2)}
    return out, source
