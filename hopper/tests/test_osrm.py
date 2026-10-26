"""OSRM parsing and leg refinement — sample payloads only, no network."""
import pytest

from app import agents, osrm, tools
from app.live import FeedError

SAMPLE = {"code": "Ok", "routes": [{"distance": 2184.0, "duration": 1747.0, "geometry": {
    "type": "LineString",
    "coordinates": [[-122.3937, 37.7955], [-122.4000, 37.7990], [-122.4058, 37.8024]]}}]}


def test_parse_route_converts_units_and_flips_coordinates():
    r = osrm.parse_route(SAMPLE)
    assert r["distance_mi"] == pytest.approx(1.357, abs=0.001)
    assert r["duration_min"] == pytest.approx(29.1, abs=0.1)
    assert r["path"][0] == [37.7955, -122.3937]


def test_parse_route_rejects_errors():
    with pytest.raises(FeedError):
        osrm.parse_route({"code": "NoRoute", "routes": []})


def test_real_distance_drives_walk_numbers():
    est = tools.walk_leg("ferry_building", "coit_tower")
    real = tools.walk_leg("ferry_building", "coit_tower", dist=1.357,
                          path=osrm.parse_route(SAMPLE)["path"], source="osrm.foot")
    assert real.distance_mi > est.distance_mi
    assert real.minutes > est.minutes and real.kcal > est.kcal and real.steps > est.steps
    assert len(real.path) == 3 and real.source == "osrm.foot"


def test_ride_uses_free_flow_time_times_traffic():
    noon = tools.ride_leg("ferry_building", "coit_tower", hour=12, dist=1.57, free_flow_min=6)
    rush = tools.ride_leg("ferry_building", "coit_tower", hour=17, dist=1.57, free_flow_min=6)
    assert noon.minutes == pytest.approx(6 * 1.35, abs=0.1)
    assert rush.minutes > noon.minutes


def test_routing_agent_swaps_legs(monkeypatch):
    monkeypatch.delenv("HOPPER_OFFLINE", raising=False)
    monkeypatch.setattr(osrm, "route", lambda mode, a, b: {**osrm.parse_route(SAMPLE), "cache": "live"})
    req = {**agents.DEFAULTS, "hour": 12, "event": False}
    trip = tools.Trip([tools.walk_leg("ferry_building", "coit_tower")], "test")
    trace = agents.Trace()
    assert agents.routing_agent([trip], req, trace) == "Street routes (OSRM)"
    assert trip.legs[0].source == "osrm.foot" and len(trip.legs[0].path) == 3


def test_routing_agent_keeps_estimates_when_osrm_fails(monkeypatch):
    monkeypatch.delenv("HOPPER_OFFLINE", raising=False)

    def boom(*_):
        raise FeedError("down")
    monkeypatch.setattr(osrm, "route", boom)
    req = {**agents.DEFAULTS, "hour": 12, "event": False}
    trip = tools.Trip([tools.walk_leg("ferry_building", "coit_tower")], "test")
    assert agents.routing_agent([trip], req, agents.Trace()).startswith("estimated")
    assert trip.legs[0].source == "walk_leg"


ORS_SAMPLE = {"type": "FeatureCollection", "features": [{
    "properties": {"summary": {"distance": 2184.0, "duration": 1747.0}},
    "geometry": {"type": "LineString", "coordinates": [[-122.3937, 37.7955, 3.0], [-122.4058, 37.8024, 80.0]]}}]}


def test_parse_ors_matches_osrm_shape():
    r = osrm.parse_ors(ORS_SAMPLE)
    assert r["engine"] == "ors" and r["path"] == [[37.7955, -122.3937], [37.8024, -122.4058]]
    assert r["distance_mi"] == pytest.approx(1.357, abs=0.001)


def test_ors_used_when_osrm_refuses_and_key_set(monkeypatch):
    monkeypatch.setattr(osrm, "_osrm_down_until", 0.0)
    monkeypatch.setenv("ORS_API_KEY", "ors-test-key-not-real")

    def refused(mode, a, b):
        raise FeedError("URLError: <urlopen error [Errno 61] Connection refused>")
    seen = {}

    def fake_post(url, body, headers=None, **kw):
        seen.update(url=url, headers=headers, cache_key=kw.get("cache_key"))
        return ORS_SAMPLE, {"cache": "live"}
    monkeypatch.setattr(osrm, "_osrm", refused)
    monkeypatch.setattr(osrm, "post_json", fake_post)
    r = osrm.route("walk", [37.7955, -122.3937], [37.8024, -122.4058])
    assert r["engine"] == "ors" and "foot-walking" in seen["url"]
    assert seen["headers"]["Authorization"] == "ors-test-key-not-real"
    assert "application/geo+json" in seen["headers"]["Accept"]          # ORS 406s a JSON-only Accept
    assert "ors-test-key-not-real" not in seen["url"] and "ors-test-key-not-real" not in seen["cache_key"]
    assert osrm._osrm_down_until > 0                            # OSRM skipped for a while after a refusal


def test_without_ors_key_osrm_errors_propagate(monkeypatch):
    monkeypatch.setattr(osrm, "_osrm_down_until", 0.0)
    monkeypatch.delenv("ORS_API_KEY", raising=False)

    def refused(mode, a, b):
        raise FeedError("Connection refused")
    monkeypatch.setattr(osrm, "_osrm", refused)
    with pytest.raises(FeedError):
        osrm.route("ride", [37.79, -122.39], [37.80, -122.40])
