"""511 SF Bay open data (https://511.org/open-data): real-time arrivals and service alerts.

Free key from 511.org → env var FIVE11_API_KEY. The free tier allows ~60 calls/hour, so:
  * stop lists are cached on disk for a day (one call per line per day),
  * StopMonitoring answers are cached 90 s and capped per plan,
  * service alerts are cached 10 min per operator,
  * a rolling hourly budget (default 50) stops calls before 511 starts refusing them.
Without a key every function returns None and the planner keeps schedule headways.
"""
import math
import os
from datetime import datetime, timezone

from .live import Budget, FeedError, get_json

BASE = "https://api.511.org/transit"
OPERATOR = {"muni": "SF", "cable": "SF", "bart": "BA"}
BUDGET = Budget(int(os.environ.get("FIVE11_HOURLY_BUDGET", "50")))
STOP_RADIUS_M = 300


def api_key():
    return os.environ.get("FIVE11_API_KEY") or os.environ.get("API_511_KEY")


def enabled():
    return bool(api_key())


def _get(path, ttl, disk_ttl=None, **params):
    return get_json(f"{BASE}/{path}", {"api_key": api_key(), "format": "json", **params},
                    ttl=ttl, disk_ttl=disk_ttl, budget=BUDGET, redact=("api_key",))


def _meters(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


# ── Parsers (pure, unit-tested against sample payloads) ──────────────────────

def parse_stops(payload):
    """511 /transit/stops → [{code, name, lat, lon}]."""
    pts = (((payload or {}).get("Contents") or {}).get("dataObjects") or {}) \
        .get("ScheduledStopPoint") or []
    if isinstance(pts, dict):
        pts = [pts]
    out = []
    for p in pts:
        loc = p.get("Location") or {}
        try:
            out.append({"code": str(p["id"]), "name": p.get("Name", ""),
                        "lat": float(loc["Latitude"]), "lon": float(loc["Longitude"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parse_stop_monitoring(payload, now=None):
    """511 /transit/StopMonitoring (SIRI) → [{line, direction, destination_ref,
    destination, minutes}] sorted by minutes until arrival."""
    now = now or datetime.now(timezone.utc)
    delivery = ((payload or {}).get("ServiceDelivery") or {}).get("StopMonitoringDelivery") or {}
    if isinstance(delivery, list):
        delivery = delivery[0] if delivery else {}
    visits = delivery.get("MonitoredStopVisit") or []
    if isinstance(visits, dict):
        visits = [visits]
    out = []
    for v in visits:
        j = v.get("MonitoredVehicleJourney") or {}
        call = j.get("MonitoredCall") or {}
        when = call.get("ExpectedArrivalTime") or call.get("AimedArrivalTime") \
            or call.get("ExpectedDepartureTime") or call.get("AimedDepartureTime")
        if not when:
            continue
        try:
            t = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError:
            continue
        minutes = (t - now).total_seconds() / 60
        if minutes < -0.5:
            continue
        out.append({"line": str(j.get("LineRef", "")), "direction": j.get("DirectionRef", ""),
                    "destination_ref": str(j.get("DestinationRef", "")),
                    "destination": j.get("DestinationName", ""),
                    "minutes": round(max(minutes, 0), 1),
                    "realtime": bool(call.get("ExpectedArrivalTime"))})
    return sorted(out, key=lambda x: x["minutes"])


def parse_alerts(payload):
    """511 /transit/servicealerts (GTFS-RT as JSON) → {route_id: [header text]}.

    Walks the document case-insensitively so small schema differences don't break it."""
    alerts = {}

    def text_of(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() == "text" and isinstance(v, str):
                    return v
                found = text_of(v)
                if found:
                    return found
        if isinstance(node, list):
            for item in node:
                found = text_of(item)
                if found:
                    return found
        return ""

    def walk(node):
        if isinstance(node, dict):
            lower = {k.lower(): v for k, v in node.items()}
            if "informedentities" in lower or "informed_entity" in lower:
                ents = lower.get("informedentities") or lower.get("informed_entity") or []
                header = text_of(lower.get("headertext") or lower.get("header_text") or {})
                for e in ents if isinstance(ents, list) else [ents]:
                    rid = {k.lower(): v for k, v in e.items()}.get("routeid") \
                        or {k.lower(): v for k, v in e.items()}.get("route_id")
                    if rid and header:
                        alerts.setdefault(str(rid), [])
                        if header not in alerts[str(rid)]:
                            alerts[str(rid)].append(header)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return alerts


# ── Live lookups ─────────────────────────────────────────────────────────────

def stops_for(operator, line_id=None):
    params = {"operator_id": operator}
    if line_id:
        params["line_id"] = line_id
    data, _ = _get("stops", ttl=86400, disk_ttl=86400, **params)
    return parse_stops(data)


def next_arrival(mode, line_id, board_latlon, alight_latlon, max_calls=2):
    """Minutes until the next vehicle on this line at the boarding stop, heading toward the
    alighting stop. Returns a dict, or None when 511 is unavailable or has no prediction."""
    if not enabled():
        return None
    operator = OPERATOR.get(mode)
    if not operator:
        return None
    try:
        stops = stops_for(operator, None if mode == "bart" else line_id)
    except FeedError:
        return None
    by_code = {s["code"]: s for s in stops}
    (blat, blon), (alat, alon) = board_latlon, alight_latlon
    near = sorted((_meters(blat, blon, s["lat"], s["lon"]), s) for s in stops)
    near = [s for d, s in near if d <= STOP_RADIUS_M][:max_calls]
    for stop in near:
        try:
            data, meta = _get("StopMonitoring", ttl=90, agency=operator, stopCode=stop["code"])
        except FeedError:
            return None
        for v in parse_stop_monitoring(data):
            if mode != "bart" and v["line"] and v["line"] != line_id:
                continue
            # Direction check: the vehicle's final stop must be nearer the alighting stop
            # than the boarding stop is. Unknown destinations are accepted.
            dest = by_code.get(v["destination_ref"])
            if dest and _meters(alat, alon, dest["lat"], dest["lon"]) > \
                    _meters(blat, blon, dest["lat"], dest["lon"]):
                continue
            return {"wait_min": v["minutes"], "stop": stop["name"], "stop_code": stop["code"],
                    "toward": v["destination"], "realtime": v["realtime"],
                    "cache": meta["cache"]}
    return None


def alerts(mode):
    """{route_id: [header]} for the mode's operator, or {} when unavailable."""
    operator = OPERATOR.get(mode)
    if not enabled() or not operator:
        return {}
    try:
        data, _ = _get("servicealerts", ttl=600, agency=operator)
    except FeedError:
        return {}
    return parse_alerts(data)


def status():
    return {"enabled": enabled(), "calls_last_hour": BUDGET.used, "budget": BUDGET.per_hour}
