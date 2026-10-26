"""Door-to-door trips with a flight in the middle.

Real airports (OurAirports, public domain, bundled in fixtures/airports.json). Flight
times and fares are ESTIMATES — free sources don't publish schedules or prices — so every
option links to Google Flights, Skyscanner, and Kayak, prefilled, for live fares. The ground
legs to and from the airports are planned by Hopper's normal swarm (so "BART to SFO" or
"Piccadilly line from Heathrow" are real routes).
"""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import duffel, tools
from .live import FeedError

FIXTURE = Path(__file__).parent / "fixtures" / "airports.json"
ROUTES = Path(__file__).parent / "fixtures" / "routes.json"   # OpenFlights nonstop routes (ODbL)
_AIRPORTS = None
_ROUTES = None
CONNECTION_MIN = 90            # added to a one-stop estimate: second takeoff/landing + layover
CRUISE_KMH = 780
MODE_LABELS = {"ride": "Ride", "walk": "Walk", "bike": "Bike", "ebike": "E-bike", "muni": "Muni", "bart": "BART",
               "cable": "Cable car", "bus": "Bus", "tram": "Tram", "metro": "Metro", "rail": "Train", "ferry": "Ferry"}


def airports():
    global _AIRPORTS
    if _AIRPORTS is None:
        data = json.loads(FIXTURE.read_text())
        _AIRPORTS = [dict(zip(data["fields"], row)) for row in data["airports"]]
    return _AIRPORTS


def routes():
    global _ROUTES
    if _ROUTES is None:
        _ROUTES = {k: set(v.split()) for k, v in json.loads(ROUTES.read_text())["routes"].items()}
    return _ROUTES


def nonstop(a, b):
    return b in routes().get(a, ())


def km_between(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def nearest_airports(lat, lon, n=2, max_km=160):
    """Best nearby airports: big hubs get a 30 km head start over small regional fields."""
    scored = []
    for a in airports():
        d = km_between((lat, lon), (a["lat"], a["lon"]))
        if d <= max_km:
            scored.append((d - (30 if a["large"] else 0), d, a))
    scored.sort(key=lambda x: x[0])
    return [{**a, "km_away": round(d, 1)} for _, d, a in scored[:n]]


def flight_estimate(dep, arr, stops=0):
    """Block time and an economy fare range from great-circle distance (labelled estimates)."""
    km = km_between((dep["lat"], dep["lon"]), (arr["lat"], arr["lon"]))
    block = 25 + 15 + km / CRUISE_KMH * 60                     # taxi + climb/descent + cruise
    intl = dep["country"] != arr["country"]
    base = (60 + 0.085 * km) if km < 1500 else (120 + 0.065 * km)
    base *= 1.2 if intl else 1.0
    if stops:
        block += CONNECTION_MIN * stops
        base *= 1.15
    r5 = lambda x: int(5 * round(x / 5))                       # noqa: E731
    return {"km": round(km), "minutes": r5(block), "international": intl, "stops": stops,
            "fare_low": r5(base * 0.75), "fare_high": r5(base * 1.6),
            "buffer_before": 150 if intl else 90, "buffer_after": 50 if intl else 25}


def links(dep, arr, date):
    d = date.strftime("%Y-%m-%d")
    return {
        "google_flights": f"https://www.google.com/travel/flights?q={quote(f'Flights from {dep} to {arr} on {d}')}",
        "skyscanner": f"https://www.skyscanner.com/transport/flights/{dep.lower()}/{arr.lower()}/{date.strftime('%y%m%d')}/",
        "kayak": f"https://www.kayak.com/flights/{dep}-{arr}/{d}",
    }


def great_circle(a, b, steps=48):
    """Points along the flight's great-circle arc for the map."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = 2 * math.asin(math.sqrt(math.sin((lat2 - lat1) / 2) ** 2 +
                                math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2))
    if d == 0:
        return [list(a), list(b)]
    pts = []
    for i in range(steps + 1):
        f = i / steps
        A, B = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = A * math.cos(lat1) * math.cos(lon1) + B * math.cos(lat2) * math.cos(lon2)
        y = A * math.cos(lat1) * math.sin(lon1) + B * math.cos(lat2) * math.sin(lon2)
        z = A * math.sin(lat1) + B * math.sin(lat2)
        pts.append([round(math.degrees(math.atan2(z, math.hypot(x, y))), 4), round(math.degrees(math.atan2(y, x)), 4)])
    return pts


def _ground(plan_fn, frm, to, hour, weight_kg, mode="hustle"):
    """Fastest ground trip between a place and an airport, via the normal planner (no LLM)."""
    try:
        result, *_ = plan_fn({"origin_place": frm, "destination_place": to, "hour": hour, "weather": "live",
                              "mode": mode, "weight_kg": weight_kg, "_quick": True})
    except Exception as e:  # noqa: BLE001 — a failed ground leg shouldn't sink the whole flight search
        return {"ok": False, "error": str(e)[:120]}
    # Respect the rider's Mode on the ground too (Broke takes BART to SFO, Hustle takes a ride).
    best = result["options"][0]
    modes = []
    for leg in best["legs"]:
        if leg["mode"] == "walk" and len(best["legs"]) > 1:
            continue                                   # "BART, then Bus 37" reads better than walk/BART/walk
        label = MODE_LABELS.get(leg["mode"], leg["mode"].title())
        name = f"{label} {leg['line_id']}".strip() if leg.get("line_id") and leg["mode"] not in ("bart", "ride") else label
        if not modes or modes[-1] != name:
            modes.append(name)
    return {"ok": True, "minutes": round(best["total_min"]), "cost": best["cost"], "summary": ", then ".join(modes),
            "legs": [{"mode": l["mode"], "path": l["path"], "color": l.get("color", "")} for l in best["legs"]]}


def plan(origin_key, dest_key, date, hour, weight_kg, plan_fn, tz_origin, tz_dest, mode="hustle"):
    """Door-to-door flight options: ground → airport buffer → flight → arrival buffer → ground."""
    o, d = tools.latlon(origin_key), tools.latlon(dest_key)
    deps, arrs = nearest_airports(*o, n=3), nearest_airports(*d, n=3)
    if not deps or not arrs:
        missing = "your start" if not deps else "your destination"
        return {"options": [], "error": f"No airport with scheduled flights within 160 km of {missing}."}
    pairs = [(a, b) for a in deps for b in arrs if a["iata"] != b["iata"]]
    if not pairs:
        return {"options": [], "error": "Both places use the same airport — this trip is better by ground."}
    # Only estimate flights that exist: nonstop pairs when there are any, else one-stop trips
    # between airports that have scheduled routes at all (Boeing Field has no SFO service).
    direct = [(a, b, 0) for a, b in pairs if nonstop(a["iata"], b["iata"])]
    pairs = direct or [(a, b, 1) for a, b in pairs if routes().get(a["iata"]) and routes().get(b["iata"])]
    if not pairs:
        return {"options": [], "error": "No scheduled flights from the airports near these places."}

    place = lambda a: {"name": f"{a['name']} ({a['iata']})", "lat": a["lat"], "lon": a["lon"]}  # noqa: E731
    o_place = {"name": tools.name(origin_key), "lat": o[0], "lon": o[1]}
    d_place = {"name": tools.name(dest_key), "lat": d[0], "lon": d[1]}
    with ThreadPoolExecutor(max_workers=6) as pool:
        deps = [a for a in deps if any(p[0] is a for p in pairs)]
        arrs = [b for b in arrs if any(p[1] is b for p in pairs)]
        to_air = {a["iata"]: pool.submit(_ground, plan_fn, o_place, place(a), hour, weight_kg, mode) for a in deps}
        # Destination-side ground trips are planned for the rough local arrival hour.
        from_air = {}
        for b in arrs:
            est = flight_estimate(deps[0], b)
            leave = datetime.combine(date, datetime.min.time(), ZoneInfo(tz_origin)).replace(hour=hour)
            land = (leave + timedelta(minutes=45 + est["buffer_before"] + est["minutes"])).astimezone(ZoneInfo(tz_dest))
            from_air[b["iata"]] = pool.submit(_ground, plan_fn, place(b), d_place, land.hour, weight_kg, mode)
        to_air = {k: f.result() for k, f in to_air.items()}
        from_air = {k: f.result() for k, f in from_air.items()}

    options = []
    for a, b, stops in pairs:
        f = flight_estimate(a, b, stops)
        g1, g2 = to_air[a["iata"]], from_air[b["iata"]]
        g1_min = g1["minutes"] if g1["ok"] else 60
        g2_min = g2["minutes"] if g2["ok"] else 60
        total = g1_min + f["buffer_before"] + f["minutes"] + f["buffer_after"] + g2_min
        ground_cost = (g1.get("cost") or 0) + (g2.get("cost") or 0)
        options.append({
            "dep": {k: a[k] for k in ("iata", "name", "city", "country", "lat", "lon", "km_away")},
            "arr": {k: b[k] for k in ("iata", "name", "city", "country", "lat", "lon", "km_away")},
            "flight": f, "ground_to": g1, "ground_from": g2, "total_min": round(total),
            "total_low": round(f["fare_low"] + ground_cost), "total_high": round(f["fare_high"] + ground_cost),
            "arc": great_circle((a["lat"], a["lon"]), (b["lat"], b["lon"])),
            "links": links(a["iata"], b["iata"], date),
        })
    # Broke ranks by price, Hustle/Burn by door-to-door time.
    rank = (lambda x: (x["total_low"], x["total_min"])) if mode == "broke" else (lambda x: (x["total_min"], x["total_low"]))
    options.sort(key=rank)

    if not duffel.enabled():
        return {"options": options[:3], "error": None, "fares_source": "estimate",
                "fares_note": "Estimated from distance. Add a Duffel API key for real flight offers."}
    real, problems = _real_offers(options[:3], date)
    if not real:
        return {"options": options[:3], "error": None, "fares_source": "estimate",
                "fares_note": f"Live fares unavailable ({problems or 'no offers for this date'}), so these are estimates."}
    real.sort(key=rank)
    return {"options": real[:4], "error": None,
            "fares_source": "duffel_test" if duffel.test_mode() else "duffel_live",
            "fares_note": ("Duffel test mode: sample airline data, not bookable fares." if duffel.test_mode()
                           else "Live fares from Duffel. Offers expire in about 30 minutes.")}


def _clock(dt):
    return dt.strftime("%-I:%M %p").lower()


def _real_offers(estimates, date):
    """Swap estimates for real Duffel offers (cheapest + fastest per airport pair).
    Door-to-door times use the real departure and arrival times."""
    def fetch(opt):
        try:
            return opt, duffel.search(opt["dep"]["iata"], opt["arr"]["iata"], date.isoformat())[0], None
        except FeedError as e:
            return opt, [], str(e)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, estimates))
    real, problems = [], sorted({err for _, _, err in results if err})
    for est, offers, _ in results:
        if not offers:
            continue
        picks = {offers[0]["id"]: offers[0]}                                  # cheapest
        fastest = min(offers, key=lambda x: x["duration_min"] or 9999)
        picks.setdefault(fastest["id"], fastest)
        for off in picks.values():
            g1, g2, f = est["ground_to"], est["ground_from"], est["flight"]
            g1_min = g1["minutes"] if g1["ok"] else 60
            g2_min = g2["minutes"] if g2["ok"] else 60
            dep = datetime.fromisoformat(off["departing_at"])
            arr = datetime.fromisoformat(off["arriving_at"])
            ground_cost = (g1.get("cost") or 0) + (g2.get("cost") or 0)
            usd = off["currency"] == "USD"
            leave_home = dep - timedelta(minutes=f["buffer_before"] + g1_min)
            at_door = arr + timedelta(minutes=f["buffer_after"] + g2_min)
            real.append({**est, "offer": {**off, "leave_by": _clock(leave_home), "at_door": _clock(at_door),
                                          "dep_local": _clock(dep), "arr_local": _clock(arr),
                                          "arrives_next_day": arr.date() > dep.date()},
                         "total_min": round(g1_min + f["buffer_before"] + (off["duration_min"] or f["minutes"])
                                            + f["buffer_after"] + g2_min),
                         "total_low": round(off["price"] + (ground_cost if usd else 0)),
                         "total_high": round(off["price"] + (ground_cost if usd else 0)),
                         "price_currency": off["currency"]})
    return real, "; ".join(problems)


def far_apart(origin_key, dest_key, miles=100):
    return tools.haversine_mi(origin_key, dest_key) > miles

