"""Live Bay Wheels dock availability from the public GBFS feed (no key)."""
import math

from .live import FeedError, get_json

GBFS = "https://gbfs.lyft.com/gbfs/2.3/bay/en/{feed}.json"
MATCH_RADIUS_M = 250


def _meters(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def stations():
    info, _ = get_json(GBFS.format(feed="station_information"), ttl=86400, disk_ttl=86400)
    status, meta = get_json(GBFS.format(feed="station_status"), ttl=60)
    by_id = {s["station_id"]: s for s in status["data"]["stations"]}
    out = []
    for s in info["data"]["stations"]:
        st = by_id.get(s["station_id"])
        if st:
            out.append((s, st))
    return out, meta["cache"]


def status_near(lat, lon):
    """Availability at the nearest live station within MATCH_RADIUS_M, or None."""
    rows, cache = stations()
    best, best_d = None, MATCH_RADIUS_M
    for info, st in rows:
        d = _meters(lat, lon, info["lat"], info["lon"])
        if d < best_d:
            best, best_d = (info, st), d
    if not best:
        return None
    info, st = best
    renting = bool(st.get("is_renting", 1))
    returning = bool(st.get("is_returning", 1))
    ebikes = st.get("num_ebikes_available", 0) if renting else 0
    total = st.get("num_bikes_available", 0) if renting else 0
    return {
        # num_bikes_available counts e-bikes too; classic = total − e-bikes.
        "classic": max(total - ebikes, 0),
        "ebike": ebikes,
        "open_docks": st.get("num_docks_available", 0) if returning else 0,
        "station": info["name"],
        "meters": round(best_d),
        "source": "GBFS live",
        "cache": cache,
    }


__all__ = ["status_near", "FeedError"]
