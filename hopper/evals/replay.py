"""Record / replay for the world feeds, so world and flight evals stay offline and reproducible.

`python -m evals.run --record` makes real calls to Transitous, CityBikes, Open-Meteo and the
elevation services once, and saves the answers to fixtures/world_cassette.json. Every
other run replays that file: same itineraries, same bikes, same clock. A request that isn't
in the cassette fails like an outage (FeedError), so a planner change that asks for new data
shows up as an eval failure, not a silent network call.
"""
import json
import os
import urllib.parse
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app import duffel, geo, live, tools, world
from app.live import FeedError

CASSETTE = Path(__file__).parent / "fixtures" / "world_cassette.json"
IGNORED_PARAMS = {"time"}       # Transitous departure time: pinned by the frozen clock instead
KEEP_KM = 3.0                   # bike stations / networks kept around the eval's places


def _key(url, params):
    kept = sorted((k, str(v)) for k, v in (params or {}).items() if k not in IGNORED_PARAMS)
    return url + "?" + urllib.parse.urlencode(kept)


def _trim(url, data, points):
    """Keep the cassette small: only bike data near the places the evals plan around."""
    near = lambda lat, lon, km: any(world._km([lat, lon], p) <= km for p in points)  # noqa: E731
    if url == world.CITYBIKES:
        return {"networks": [n for n in data.get("networks", [])
                             if near(n["location"]["latitude"], n["location"]["longitude"], 60)]}
    if url.startswith(world.CITYBIKES + "/"):
        net = {k: v for k, v in data.get("network", {}).items() if k in ("id", "name")}
        net["stations"] = [{**{k: s.get(k) for k in ("name", "latitude", "longitude", "free_bikes", "empty_slots")},
                            "extra": {"ebikes": (s.get("extra") or {}).get("ebikes", 0)}}
                           for s in data.get("network", {}).get("stations", [])
                           if near(s["latitude"], s["longitude"], KEEP_KM)]
        return {"network": net}
    if url == world.TRANSITOUS:               # only the fields world.itineraries_to_trips reads
        place = lambda p: {k: p.get(k) for k in ("name", "lat", "lon")}  # noqa: E731
        leg_keys = ("mode", "startTime", "endTime", "legGeometry", "headsign", "realTime", "routeColor",
                    "routeLongName", "routeShortName", "displayName")
        return {"itineraries": [{"legs": [{**{k: l[k] for k in leg_keys if k in l},
                                           "from": place(l.get("from") or {}), "to": place(l.get("to") or {})}
                                          for l in it.get("legs", [])]} for it in data.get("itineraries", [])]}
    return data


@contextmanager
def cassette(points, record=False):
    """Patch the world feeds to replay (or record) the cassette and freeze the clock."""
    tape = json.loads(CASSETTE.read_text()) if CASSETTE.exists() and not record else \
        {"now": datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat(), "responses": {}}
    frozen = datetime.fromisoformat(tape["now"])
    real_get = live.get_json

    def get_json(url, params=None, **kw):
        k = _key(url, params)
        if record:
            if k not in tape["responses"]:
                data, _ = real_get(url, params, **kw)
                tape["responses"][k] = _trim(url, data, points)
            return tape["responses"][k], {"cache": "recorded"}
        if k not in tape["responses"]:
            raise FeedError(f"not in eval cassette: {url}")
        return tape["responses"][k], {"cache": "replay"}

    def local_now(tz):
        try:
            return frozen.astimezone(ZoneInfo(tz))
        except Exception:  # noqa: BLE001
            return frozen

    saved = (world.get_json, geo.get_json, world.local_now, duffel.enabled, os.environ.get("HOPPER_OFFLINE"),
             os.environ.get("HOPPER_NO_OSRM"))
    world.get_json = geo.get_json = get_json
    world.local_now = local_now
    duffel.enabled = lambda: False          # fares stay estimates: deterministic, no keys needed
    if record:                              # real network for the world feeds, nothing else
        os.environ["HOPPER_OFFLINE"], os.environ["HOPPER_NO_OSRM"] = "0", "1"
    try:
        yield tape
    finally:
        world.get_json, geo.get_json, world.local_now, duffel.enabled = saved[:4]
        for name, val in (("HOPPER_OFFLINE", saved[4]), ("HOPPER_NO_OSRM", saved[5])):
            if val is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = val
        if record:
            CASSETTE.parent.mkdir(exist_ok=True)
            CASSETTE.write_text(json.dumps(tape, separators=(",", ":"), sort_keys=True))


def points_of(places):
    return [[p["lat"], p["lon"]] for p in places] + [tools.latlon(k) for k in ("sfo", "union_square")]
