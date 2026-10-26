"""Real street routes on OpenStreetMap data: OSRM first, OpenRouteService as the fallback.

- OSRM: the public FOSSGIS servers (routing.openstreetmap.de), which run separate foot, bike,
  and car profiles — the project-osrm.org demo is car-only. Shared community servers: results
  are cached for a day on disk, each plan only routes the legs the rider will see, and a
  rolling budget keeps usage polite. Override with OSRM_BASE_URL (e.g. a local
  `osrm-backend` container) for heavier use.
- OpenRouteService: used when OSRM fails or refuses (it rate-limits bursts) and ORS_API_KEY is
  set (free key: 2,000 routes/day). The key travels in the Authorization header, never in a
  URL, log line, or cache key. After an OSRM refusal, OSRM is skipped for a few minutes so
  plans don't keep waiting on it.
"""
import os
import time

from .live import Budget, FeedError, get_json, post_json

BASE = os.environ.get("OSRM_BASE_URL", "https://routing.openstreetmap.de")
PROFILE = {"walk": "foot", "bike": "bike", "ebike": "bike", "ride": "car"}
ORS_PROFILE = {"walk": "foot-walking", "bike": "cycling-regular", "ebike": "cycling-electric", "ride": "driving-car"}
ORS_API = "https://api.openrouteservice.org/v2/directions/{profile}/geojson"
BUDGET = Budget(int(os.environ.get("OSRM_HOURLY_BUDGET", "600")))
ORS_BUDGET = Budget(int(os.environ.get("ORS_HOURLY_BUDGET", "80")))     # free tier ≈ 2,000/day
OSRM_COOLDOWN_S = 300
M_TO_MI = 1 / 1609.34
_osrm_down_until = 0.0


def ors_key():
    return (os.environ.get("ORS_API_KEY") or "").strip()


def parse_route(payload):
    """OSRM /route response → {distance_mi, duration_min, path [[lat, lon], ...]}."""
    if (payload or {}).get("code") != "Ok" or not payload.get("routes"):
        raise FeedError(f"OSRM: {(payload or {}).get('code', 'no response')}")
    r = payload["routes"][0]
    coords = r["geometry"]["coordinates"]            # GeoJSON is [lon, lat]
    return {"distance_mi": r["distance"] * M_TO_MI, "duration_min": r["duration"] / 60,
            "path": [[round(lat, 6), round(lon, 6)] for lon, lat in coords], "engine": "osrm"}


def parse_ors(payload):
    """OpenRouteService GeoJSON directions → same shape as parse_route."""
    try:
        f = payload["features"][0]
        s = f["properties"]["summary"]
        coords = f["geometry"]["coordinates"]
    except (KeyError, IndexError, TypeError):
        raise FeedError("OpenRouteService: no route") from None
    return {"distance_mi": s.get("distance", 0) * M_TO_MI, "duration_min": s.get("duration", 0) / 60,
            "path": [[round(lat, 6), round(lon, 6)] for lon, lat, *_ in coords], "engine": "ors"}


def _osrm(mode, a, b):
    (alat, alon), (blat, blon) = a, b
    # FOSSGIS serves each profile under its own prefix; the path segment stays "driving".
    url = f"{BASE}/routed-{PROFILE[mode]}/route/v1/driving/{alon:.5f},{alat:.5f};{blon:.5f},{blat:.5f}"
    params = {"overview": "full", "geometries": "geojson"}
    try:
        data, meta = get_json(url, params, ttl=86400, disk_ttl=86400, budget=BUDGET, timeout=6)
    except FeedError as e:
        if "429" not in str(e):
            raise
        time.sleep(1.0)            # shared server asked us to slow down — one polite retry
        data, meta = get_json(url, params, ttl=86400, disk_ttl=86400, budget=BUDGET, timeout=6)
    return {**parse_route(data), "cache": meta["cache"]}


def _ors(mode, a, b):
    (alat, alon), (blat, blon) = a, b
    if not ORS_BUDGET.take():
        raise FeedError("OpenRouteService hourly budget spent")
    body = {"coordinates": [[round(alon, 5), round(alat, 5)], [round(blon, 5), round(blat, 5)]]}
    data, meta = post_json(ORS_API.format(profile=ORS_PROFILE[mode]), body,
                           # The /geojson endpoint answers application/geo+json and 406s a plain JSON Accept.
                           headers={"Authorization": ors_key(), "Accept": "application/geo+json, application/json"},
                           ttl=86400,
                           cache_key=f"ors:{mode}:{body['coordinates']}", timeout=10)
    return {**parse_ors(data), "cache": meta["cache"]}


def route(mode, a_latlon, b_latlon):
    """Street route for a leg mode between two [lat, lon] points. Raises FeedError."""
    global _osrm_down_until
    if mode not in PROFILE:
        raise FeedError(f"no routing profile for {mode}")
    osrm_error = None
    if time.time() >= _osrm_down_until:
        try:
            return _osrm(mode, a_latlon, b_latlon)
        except FeedError as e:
            osrm_error = e
            if "Connection refused" in str(e) or "429" in str(e) or "timed out" in str(e).lower():
                _osrm_down_until = time.time() + OSRM_COOLDOWN_S
    if ors_key():
        return _ors(mode, a_latlon, b_latlon)
    raise osrm_error or FeedError("OSRM cooling down after refusals; set ORS_API_KEY for a fallback")
