"""Worldwide data sources (all free, no API key). San Francisco keeps its richer local
stack (511, Bay Wheels, NWS, hand-built lines); everywhere else uses these:

- Transit: Transitous (api.transitous.org) — community MOTIS router over worldwide GTFS
  feeds, with real-time where agencies publish it. No fares, so transit cost is an estimate.
- Weather + local time zone: Open-Meteo forecast (timezone=auto).
- Elevation: Open-Meteo elevation.
- Bike share: CityBikes (api.citybik.es) — ~800 networks worldwide.
- Bars: Overpass around a point (live; SF uses the bundled snapshot).
"""
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import geo, tools
from .live import Budget, FeedError, get_json

TRANSITOUS = "https://api.transitous.org/api/v1/plan"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ELEV = "https://api.open-meteo.com/v1/elevation"
CITYBIKES = "https://api.citybik.es/v2/networks"
OVERPASS = "https://overpass-api.de/api/interpreter"
TRANSITOUS_BUDGET = Budget(300)
TRANSIT_FARE_ESTIMATE = 2.75          # USD-ish; Transitous has no fare data
SF_TZ = "America/Los_Angeles"

MODE_MAP = {"SUBWAY": "metro", "METRO": "metro", "BUS": "bus", "COACH": "bus", "TROLLEYBUS": "bus",
            "TRAM": "tram", "CABLE_CAR": "cable", "FUNICULAR": "tram", "AERIAL_LIFT": "tram",
            "FERRY": "ferry", "RAIL": "rail", "REGIONAL_RAIL": "rail", "REGIONAL_FAST_RAIL": "rail",
            "HIGHSPEED_RAIL": "rail", "LONG_DISTANCE": "rail", "NIGHT_RAIL": "rail", "SUBURBAN": "rail"}


# ── Region + local time ─────────────────────────────────────────────────────

def in_sf_area(lat, lon):
    return geo.inside_sf(lat, lon) or geo.near_sfo(lat, lon)


def region(o_key, d_key):
    """'sf' when the whole trip is inside San Francisco (+SFO), else 'world'."""
    return "sf" if all(in_sf_area(*tools.latlon(k)) for k in (o_key, d_key)) else "world"


def _rk(x):
    return f"{round(x, 2):.2f}"          # ~1 km grid for caching


def forecast(lat, lon):
    data, meta = get_json(OPEN_METEO, {
        "latitude": _rk(lat), "longitude": _rk(lon), "timezone": "auto", "forecast_days": 2,
        "hourly": "temperature_2m,precipitation_probability,weather_code,wind_speed_10m",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph"}, ttl=900, disk_ttl=900, timeout=8)
    return data, meta["cache"]


def timezone_at(lat, lon):
    if in_sf_area(lat, lon):
        return SF_TZ
    try:
        return forecast(lat, lon)[0].get("timezone") or "UTC"
    except FeedError:
        return "UTC"


def local_now(tz):
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:  # noqa: BLE001 — unknown zone names fall back to UTC
        return datetime.now(timezone.utc)


# WMO weather codes → our buckets / words
WMO_RAIN = set(range(51, 68)) | set(range(80, 83)) | {95, 96, 99}
WMO_FOG = {45, 48}
WMO_WORDS = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
             51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain",
             65: "Heavy rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers",
             81: "Rain showers", 82: "Heavy showers", 95: "Thunderstorm"}


def weather_at(lat, lon, hour):
    """Open-Meteo forecast for `hour` (local, 0–23) → same shape as weather.at()."""
    data, cache = forecast(lat, lon)
    h = data["hourly"]
    idx = next((i for i, t in enumerate(h["time"]) if int(t[11:13]) == hour), 0)
    code = int(h["weather_code"][idx] or 0)
    precip = int(h["precipitation_probability"][idx] or 0)
    condition = "rain" if (code in WMO_RAIN or precip >= 50) else "fog" if code in WMO_FOG else "clear"
    return {"condition": condition, "summary": WMO_WORDS.get(code, "Cloudy"),
            "temp_f": round(h["temperature_2m"][idx]), "wind_mph": round(h["wind_speed_10m"][idx] or 0),
            "precip_pct": precip, "source": "Open-Meteo", "cache": cache, "timezone": data.get("timezone")}


def elevation_ft(lat, lon):
    data, _ = get_json(OPEN_METEO_ELEV, {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}"},
                       ttl=86400, disk_ttl=2592000, timeout=6)
    return round(float(data["elevation"][0]) * 3.28084)


# ── Transit (Transitous) ────────────────────────────────────────────────────

def decode_polyline(points, precision=7):
    """Google-style encoded polyline → [[lat, lon], ...]."""
    coords, idx, lat, lon, factor = [], 0, 0, 0, 10 ** precision
    while idx < len(points):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(points[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append([round(lat / factor, 6), round(lon / factor, 6)])
    return coords


def _path_mi(path):
    return sum(tools.haversine_pts(a, b) for a, b in zip(path, path[1:]))


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _stop_key(p, fallback):
    try:
        return geo.register(p.get("name") or fallback, p["lat"], p["lon"])
    except (KeyError, TypeError, ValueError):
        return None


def itineraries_to_trips(payload, origin, destination, weight_kg, depart_at):
    """Transitous /plan → [Trip]. Walk legs become ordinary walk legs (our health math);
    transit legs keep the agency's line name, colour, timing, and real-time flag."""
    trips = []
    for it in (payload or {}).get("itineraries", []):
        legs, prev_end, ok, fare_charged = [], depart_at, True, False
        raw = it.get("legs", [])
        for i, L in enumerate(raw):
            geom = L.get("legGeometry") or {}
            path = decode_polyline(geom.get("points", ""), geom.get("precision", 7)) if geom.get("points") else []
            frm = origin if i == 0 else _stop_key(L.get("from", {}), "Stop")
            to = destination if i == len(raw) - 1 else _stop_key(L.get("to", {}), "Stop")
            if not frm or not to:
                ok = False
                break
            path = path or [tools.latlon(frm), tools.latlon(to)]
            start, end = _ts(L["startTime"]), _ts(L["endTime"])
            wait = max((start - prev_end).total_seconds() / 60, 0) if prev_end else 0
            if L.get("mode") == "WALK":
                leg = tools.walk_leg(frm, to, weight_kg, dist=max(_path_mi(path), 0.01), path=path,
                                     source="transitous.walk")
                leg.wait_min = round(wait, 1)
            else:
                mode = MODE_MAP.get(L.get("mode"), "bus")
                name = L.get("routeShortName") or L.get("displayName") or L.get("routeLongName") or mode.title()
                head = L.get("headsign")
                cost = 0.0 if fare_charged else TRANSIT_FARE_ESTIMATE
                fare_charged = True
                color = L.get("routeColor")
                leg = tools.Leg(mode, frm, to, round(_path_mi(path), 2), round((end - start).total_seconds() / 60, 1),
                                wait_min=round(wait, 1), cost=cost, line=f"{name}" + (f" toward {head}" if head else ""),
                                line_id=str(L.get("routeShortName") or ""), path=path, source="transitous",
                                note=("live times" if L.get("realTime") else "scheduled")
                                + (", fare estimated" if cost else ""))
                leg.color = f"#{color}" if color and re.fullmatch(r"[0-9A-Fa-f]{6}", color) else ""
            legs.append(leg)
            prev_end = end
        if ok and legs and any(l.mode != "walk" for l in legs):
            trips.append(tools.Trip(legs, "Transit (Transitous)"))
    return trips


def transit_trips(origin, destination, weight_kg, depart_at, leave_now):
    params = {"fromPlace": "{:.6f},{:.6f}".format(*tools.latlon(origin)),
              "toPlace": "{:.6f},{:.6f}".format(*tools.latlon(destination)), "numItineraries": 4}
    if not leave_now:
        params["time"] = depart_at.isoformat(timespec="seconds")
    data, _ = get_json(TRANSITOUS, params, ttl=60, budget=TRANSITOUS_BUDGET, timeout=20)
    return itineraries_to_trips(data, origin, destination, weight_kg, depart_at)


# ── Bike share (CityBikes) ──────────────────────────────────────────────────

def _km(a, b):
    return tools.haversine_pts(a, b) * 1.609


def nearest_network(lat, lon, max_km=40, candidates=4):
    """The bike-share network with a station closest to the rider. Big cities have several
    networks (NYC: Citi Bike plus smaller e-bike fleets), and a network's listed centre point
    can be far from its stations, so compare actual stations of the nearest few."""
    data, _ = get_json(CITYBIKES, {"fields": "id,name,location"}, ttl=86400, disk_ttl=86400, timeout=12)
    near = sorted((n for n in data.get("networks", [])
                   if _km([lat, lon], [n["location"]["latitude"], n["location"]["longitude"]]) <= max_km),
                  key=lambda n: _km([lat, lon], [n["location"]["latitude"], n["location"]["longitude"]]))[:candidates]
    best, best_score = None, (0, float("-inf"))
    for n in near:
        try:
            sts, _ = stations(n["id"])
        except FeedError:
            continue
        close = [s for s in sts if _km([lat, lon], [s["lat"], s["lon"]]) <= 0.7]
        # Most bikes within a short walk wins; nearest station breaks ties.
        score = (sum(s["classic"] + s["ebike"] for s in close),
                 -min((_km([lat, lon], [s["lat"], s["lon"]]) for s in sts), default=float("inf")))
        if close and score > best_score:
            best, best_score = n, score
    return best


def stations(network_id):
    data, meta = get_json(f"{CITYBIKES}/{network_id}", {}, ttl=120, timeout=12)
    out = []
    for s in data.get("network", {}).get("stations", []):
        extra = s.get("extra") or {}
        ebikes = extra.get("ebikes") or 0
        free = s.get("free_bikes") or 0
        out.append({"name": s.get("name") or "Bike station", "lat": s["latitude"], "lon": s["longitude"],
                    "classic": max(free - ebikes, 0), "ebike": ebikes, "open_docks": s.get("empty_slots") or 0})
    return out, meta["cache"]


def bike_trips(origin, destination, hour, weight_kg):
    o, d = tools.latlon(origin), tools.latlon(destination)
    net = nearest_network(*o)
    if not net:
        return [], None
    sts, _ = stations(net["id"])
    near_o = sorted((s for s in sts if s["classic"] + s["ebike"] > 0 and _km(o, [s["lat"], s["lon"]]) <= 0.7),
                    key=lambda s: _km(o, [s["lat"], s["lon"]]))[:2]
    near_d = sorted((s for s in sts if s["open_docks"] > 0 and _km(d, [s["lat"], s["lon"]]) <= 0.7),
                    key=lambda s: _km(d, [s["lat"], s["lon"]]))[:2]
    trips = []
    for a in near_o:
        for b in near_d:
            ka, kb = geo.register(a["name"], a["lat"], a["lon"]), geo.register(b["name"], b["lat"], b["lon"])
            if ka == kb:
                continue
            for ebike in (False, True):
                count = a["ebike"] if ebike else a["classic"]
                if not count:
                    continue
                ride = tools.bike_leg(ka, kb, ebike, hour, weight_kg, source="citybikes")
                ride.note = f"{count} {'e-bike' if ebike else 'bike'}{'' if count == 1 else 's'} at {a['name']} ({net['name']}), price estimated"
                legs = [tools.walk_leg(origin, ka, weight_kg), ride, tools.walk_leg(kb, destination, weight_kg)]
                trips.append(tools.Trip(legs, "Micromobility (CityBikes)"))
    return trips, net["name"]


# ── Walk-ahead pickup points along the real walking route ───────────────────

def pickup_points_along(origin, destination, every_mi=(0.3, 0.6)):
    """Points on the walking route toward the destination — ride-hail walk-ahead pickups
    that work in any city (SF also uses its landmark list)."""
    from . import osrm
    r = osrm.route("walk", tools.latlon(origin), tools.latlon(destination))
    pts, keys, walked = r["path"], [], 0.0
    targets = list(every_mi)
    for a, b in zip(pts, pts[1:]):
        walked += tools.haversine_pts(a, b)
        if targets and walked >= targets[0]:
            keys.append(geo.register(f"Pickup point {targets[0]} mi along your walk", b[0], b[1]))
            targets.pop(0)
    return keys


# ── Bars anywhere (Overpass around a point) ─────────────────────────────────

def bars_near(lat, lon, radius_m=1500):
    q = (f'[out:json][timeout:25];nwr["amenity"~"^(bar|pub|biergarten)$"]["name"]'
         f'(around:{radius_m},{lat:.4f},{lon:.4f});out center tags;')
    data, meta = get_json(OVERPASS, {"data": q}, ttl=604800, disk_ttl=604800, timeout=25)
    return data.get("elements", []), meta["cache"]
