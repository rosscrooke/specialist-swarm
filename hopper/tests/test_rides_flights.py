"""Ride types and flights — offline."""
from datetime import date
from urllib.parse import parse_qs, urlparse

from app import flights, rides
from app.server import app

PICKUP = {"name": "Ferry Building", "lat": 37.7955, "lon": -122.3937}
DROPOFF = {"name": "Coit Tower", "lat": 37.8024, "lon": -122.4058}


def test_ride_types_sorted_cheapest_available_first_with_ranges():
    opts = rides.options(PICKUP, DROPOFF, 1.57, 8, hour=14)
    avail = [o for o in opts if o["available"]]
    assert [o["price"] for o in avail] == sorted(o["price"] for o in avail)
    for o in opts:
        assert o["price_low"] < o["price"] < o["price_high"] and o["eta_min"] >= 2


def test_tier_pricing_order_and_minimums():
    by = {o["id"]: o for o in rides.options(PICKUP, DROPOFF, 3.0, 14, hour=14)}
    assert by["shared"]["price"] < by["go"]["price"] < by["comfort"]["price"] < by["xl"]["price"] < by["premium"]["price"]
    tiny = {o["id"]: o for o in rides.options(PICKUP, DROPOFF, 0.2, 2, hour=14)}
    assert tiny["premium"]["price"] >= 25.0 + 2.95


def test_shared_unavailable_late_and_in_heavy_surge_taxi_never_surges():
    late = {o["id"]: o for o in rides.options(PICKUP, DROPOFF, 2, 10, hour=23)}
    assert not late["shared"]["available"] and "late" in late["shared"]["reason"]
    surge = {o["id"]: o for o in rides.options(PICKUP, DROPOFF, 2, 10, hour=18, surge=1.9)}
    calm = {o["id"]: o for o in rides.options(PICKUP, DROPOFF, 2, 10, hour=18, surge=1.0)}
    assert not surge["shared"]["available"]
    assert surge["go"]["price"] > calm["go"]["price"] and surge["taxi"]["price"] == calm["taxi"]["price"]


def test_eta_is_deterministic_and_dropoff_time_adds_up():
    a = rides.options(PICKUP, DROPOFF, 2, 10, hour=14, now_min=840)
    b = rides.options(PICKUP, DROPOFF, 2, 10, hour=14, now_min=840)
    assert a == b
    go = next(o for o in a if o["id"] == "go")
    assert go["dropoff_min"] == 840 + go["eta_min"] + go["ride_min"]


def test_deep_links_prefill_pickup_and_dropoff():
    links = rides.deep_links(PICKUP, DROPOFF)
    u = parse_qs(urlparse(links["uber"]).query)
    assert links["uber"].startswith("https://m.uber.com/ul/?") and u["pickup[latitude]"] == ["37.7955"]
    assert u["dropoff[nickname]"] == ["Coit Tower"]
    assert parse_qs(urlparse(links["lyft"]).query)["destination[longitude]"] == ["-122.4058"]


def test_ride_options_api_validates_input():
    c = app.test_client()
    assert c.post("/api/ride-options", json={"leg": {}}).status_code == 400
    bad = {"leg": {"path": [[37.79, -122.39], [37.80, -122.40]], "distance_mi": 9999, "minutes": 5}}
    assert c.post("/api/ride-options", json=bad).status_code == 400
    ok = {"leg": {"path": [[37.79, -122.39], [37.80, -122.40]], "distance_mi": 1.2, "minutes": 6}, "hour": 9}
    r = c.post("/api/ride-options", json=ok)
    assert r.status_code == 200 and len(r.json["options"]) == len(rides.TIERS) and "simulated" in r.json["note"]


def test_nearest_airports_prefers_hubs():
    near_sf = [a["iata"] for a in flights.nearest_airports(37.7955, -122.3937, n=3)]
    # OAK is closer than SFO in a straight line from the Ferry Building; both big hubs beat
    # the small regional fields that are nearer than SJC.
    assert set(near_sf[:2]) == {"SFO", "OAK"} and "SQL" not in near_sf
    assert flights.nearest_airports(0.0, -150.0) == []          # middle of the Pacific


def test_flight_estimate_scales_with_distance_and_flags_international():
    by = {a["iata"]: a for a in flights.airports()}
    short = flights.flight_estimate(by["SFO"], by["LAX"])
    long = flights.flight_estimate(by["SFO"], by["JFK"])
    intl = flights.flight_estimate(by["SFO"], by["LHR"])
    assert short["minutes"] < long["minutes"] < intl["minutes"]
    assert short["fare_low"] < long["fare_low"] and intl["international"] and not long["international"]
    assert intl["buffer_before"] > long["buffer_before"]
    assert 4000 < long["km"] < 4300


def test_fare_links_prefilled_with_airports_and_date():
    l = flights.links("SFO", "JFK", date(2026, 11, 2))
    assert "SFO%20to%20JFK%20on%202026-11-02" in l["google_flights"]
    assert l["skyscanner"].endswith("/sfo/jfk/261102/") and l["kayak"].endswith("/SFO-JFK/2026-11-02")


def test_great_circle_arc_endpoints():
    arc = flights.great_circle((37.62, -122.37), (51.47, -0.46))
    assert arc[0] == [37.62, -122.37] and abs(arc[-1][0] - 51.47) < 1e-3 and len(arc) == 49
    assert max(p[0] for p in arc) > 55                           # arcs north over Greenland


def test_far_trips_redirect_to_flights():
    c = app.test_client()
    r = c.post("/api/plan", json={"origin": "ferry_building", "weather": "clear",
                                  "destination_place": {"name": "Times Square", "lat": 40.758, "lon": -73.9855}})
    assert r.status_code == 200 and r.json["redirect"] == "flights" and r.json["miles"] > 2000


def test_only_airport_pairs_with_service_are_estimated():
    from app import flights
    assert flights.nonstop("SFO", "SEA") and not flights.nonstop("SFO", "BFI")   # Boeing Field: no SFO flights
    sfo, sea = (next(a for a in flights.airports() if a["iata"] == c) for c in ("SFO", "SEA"))
    one_stop, direct = flights.flight_estimate(sfo, sea, stops=1), flights.flight_estimate(sfo, sea)
    assert one_stop["stops"] == 1 and one_stop["minutes"] - direct["minutes"] >= 85
    assert one_stop["fare_low"] > direct["fare_low"]
