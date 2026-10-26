"""Worldwide support — offline, with sample payloads."""
from datetime import datetime, timezone

import pytest

from app import agents, geo, tools, world


def test_decode_polyline_precision_5_reference():
    # Google's documented example: (38.5,-120.2), (40.7,-120.95), (43.252,-126.453)
    assert world.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5) == \
        [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]


def _encode(points, precision=7):
    out, plat, plon, f = [], 0, 0, 10 ** precision
    for lat, lon in points:
        for v, prev in ((round(lat * f), plat), (round(lon * f), plon)):
            d = v - prev
            d = ~(d << 1) if d < 0 else d << 1
            while d >= 0x20:
                out.append(chr((0x20 | (d & 0x1F)) + 63))
                d >>= 5
            out.append(chr(d + 63))
        plat, plon = round(lat * f), round(lon * f)
    return "".join(out)


def test_itineraries_become_trips_with_agency_line_details():
    o = geo.register("Eiffel Tower", 48.8584, 2.2945, elev=110)
    d = geo.register("Louvre Museum", 48.8606, 2.3376, elev=110)
    stop_a, stop_b = {"name": "Bir-Hakeim", "lat": 48.8539, "lon": 2.2894}, {"name": "Palais Royal", "lat": 48.8625, "lon": 2.3364}
    payload = {"itineraries": [{"legs": [
        {"mode": "WALK", "from": {"name": "start", "lat": 48.8584, "lon": 2.2945}, "to": stop_a,
         "startTime": "2026-10-24T07:00:00Z", "endTime": "2026-10-24T07:08:00Z",
         "legGeometry": {"points": _encode([(48.8584, 2.2945), (48.8539, 2.2894)]), "precision": 7}},
        {"mode": "SUBWAY", "from": stop_a, "to": stop_b, "routeShortName": "6", "headsign": "Nation",
         "routeColor": "6ECA97", "realTime": True,
         "startTime": "2026-10-24T07:12:00Z", "endTime": "2026-10-24T07:30:00Z",
         "legGeometry": {"points": _encode([(48.8539, 2.2894), (48.8625, 2.3364)]), "precision": 7}},
        {"mode": "WALK", "from": stop_b, "to": {"name": "end", "lat": 48.8606, "lon": 2.3376},
         "startTime": "2026-10-24T07:30:00Z", "endTime": "2026-10-24T07:33:00Z",
         "legGeometry": {"points": _encode([(48.8625, 2.3364), (48.8606, 2.3376)]), "precision": 7}},
    ]}]}
    depart = datetime(2026, 10, 24, 7, 0, tzinfo=timezone.utc)
    trips = world.itineraries_to_trips(payload, o, d, 75, depart)
    assert len(trips) == 1
    walk, metro, walk2 = trips[0].legs
    assert walk.mode == "walk" and walk.frm == o and walk.kcal > 0
    assert metro.mode == "metro" and metro.line == "6 toward Nation" and metro.color == "#6ECA97"
    assert metro.wait_min == 4.0 and metro.minutes == 18.0 and metro.cost == world.TRANSIT_FARE_ESTIMATE
    assert "live times" in metro.note and "fare estimated" in metro.note
    assert walk2.to == d and tools.name(metro.to) == "Palais Royal"


def test_walk_only_itineraries_are_skipped():
    o, d = geo.register("A", 48.85, 2.29), geo.register("B", 48.86, 2.30)
    payload = {"itineraries": [{"legs": [{"mode": "WALK", "from": {}, "to": {}, "startTime": "2026-10-24T07:00:00Z",
                                          "endTime": "2026-10-24T07:20:00Z", "legGeometry": {}}]}]}
    assert world.itineraries_to_trips(payload, o, d, 75, None) == []


def test_open_meteo_weather_mapping(monkeypatch):
    sample = {"timezone": "Europe/Paris", "hourly": {
        "time": ["2026-10-24T06:00", "2026-10-24T07:00"], "temperature_2m": [48.5, 50.1],
        "precipitation_probability": [10, 70], "weather_code": [3, 61], "wind_speed_10m": [8, 12]}}
    monkeypatch.setattr(world, "forecast", lambda lat, lon: (sample, "live"))
    w = world.weather_at(48.86, 2.35, 7)
    assert w == {**w, "condition": "rain", "summary": "Light rain", "temp_f": 50, "precip_pct": 70, "timezone": "Europe/Paris"}
    assert world.weather_at(48.86, 2.35, 6)["condition"] == "clear"


def test_region_detection():
    paris = geo.register("Paris", 48.8566, 2.3522)
    assert world.region("ferry_building", "coit_tower") == "sf"
    assert world.region("ferry_building", paris) == "world"
    assert world.timezone_at(37.79, -122.40) == world.SF_TZ


def test_unknown_elevation_is_treated_as_flat():
    a, b = geo.register("Stop A", 51.53, -0.12), geo.register("Stop B", 51.51, -0.08)
    leg = tools.walk_leg(a, b)
    assert leg.grade == 0 and leg.climb_ft == 0 and leg.minutes > 0


def test_outside_sf_the_intent_parser_never_guesses_sf_landmarks():
    rules = agents.parse_intent_rules("from king's cross station to tower of london", sf_context=False)
    assert "origin" not in rules and "destination" not in rules
    assert rules["origin_text"] == "king's cross station"
    assert agents.parse_intent_rules("from union square to coit tower")["destination"] == "coit_tower"


def test_trips_across_continents_hand_off_to_flights():
    result, *_ = agents.orchestrate({"origin_place": {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
                                     "destination": "ferry_building", "weather": "clear"})
    assert result["redirect"] == "flights" and result["miles"] > 5000
    with pytest.raises(agents.PlanError, match="miles apart"):      # ground legs never chain flights
        agents.orchestrate({"origin_place": {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
                            "destination": "ferry_building", "weather": "clear", "_quick": True})
