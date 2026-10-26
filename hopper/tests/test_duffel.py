"""Duffel flight offers — mocked, no network, no real key."""
from datetime import date

import pytest

from app import duffel, flights, geo
from app.live import FeedError
from app.server import app

FAKE_KEY = "duffel_test_FAKEKEY_for_tests_only"


def offer(oid, price, dep, arr, duration, segs=(("SFO", "JFK", "ZZ", "100"),), currency="USD"):
    return {"id": oid, "total_amount": str(price), "total_currency": currency, "expires_at": "2026-10-24T08:00:00Z",
            "owner": {"name": "Duffel Airways", "iata_code": "ZZ", "logo_symbol_url": "https://assets.duffel.com/zz.svg"},
            "slices": [{"duration": duration, "segments": [
                {"origin": {"iata_code": o}, "destination": {"iata_code": d},
                 "marketing_carrier": {"name": "Duffel Airways", "iata_code": c}, "marketing_carrier_flight_number": n,
                 "departing_at": dep, "arriving_at": arr} for o, d, c, n in segs]}]}


PAYLOAD = {"data": {"offers": [
    offer("off_fast", 389.10, "2026-10-25T07:00:00", "2026-10-25T15:35:00", "PT5H35M"),
    offer("off_cheap", 241.50, "2026-10-25T06:10:00", "2026-10-25T18:05:00", "PT8H55M",
          segs=(("SFO", "ORD", "ZZ", "210"), ("ORD", "JFK", "ZZ", "418"))),
    {"id": "broken", "slices": []},
]}}


def test_iso_duration_parsing():
    assert duffel.iso_minutes("PT5H35M") == 335
    assert duffel.iso_minutes("P1DT2H") == 1560
    assert duffel.iso_minutes("PT45M") == 45
    assert duffel.iso_minutes("garbage") is None


def test_parse_offers_cheapest_first_with_stops_and_flight_numbers():
    out = duffel.parse_offers(PAYLOAD)
    assert [o["id"] for o in out] == ["off_cheap", "off_fast"]          # broken offer skipped
    cheap, fast = out
    assert cheap["stops"] == 1 and cheap["via"] == ["ORD"] and cheap["flight_numbers"] == ["ZZ 210", "ZZ 418"]
    assert fast["stops"] == 0 and fast["duration_min"] == 335 and fast["price"] == 389.10 and fast["currency"] == "USD"


def test_search_without_key_raises(monkeypatch):
    monkeypatch.delenv("DUFFEL_API_KEY", raising=False)
    with pytest.raises(FeedError):
        duffel.search("SFO", "JFK", "2026-10-25")


def test_search_sends_auth_version_and_payload(monkeypatch):
    monkeypatch.setenv("DUFFEL_API_KEY", FAKE_KEY)
    seen = {}

    def fake_post(url, payload, headers=None, **kw):
        seen.update(url=url, payload=payload, headers=headers, cache_key=kw.get("cache_key"))
        return PAYLOAD, {"cache": "live"}
    monkeypatch.setattr(duffel, "post_json", fake_post)
    offers, cache = duffel.search("SFO", "JFK", "2026-10-25")
    assert len(offers) == 2 and cache == "live"
    assert seen["headers"]["Authorization"] == f"Bearer {FAKE_KEY}" and seen["headers"]["Duffel-Version"] == "v2"
    assert "return_offers=true" in seen["url"]
    assert seen["payload"]["data"]["slices"][0] == {"origin": "SFO", "destination": "JFK", "departure_date": "2026-10-25"}
    assert FAKE_KEY not in seen["cache_key"]                             # secrets never key the cache
    assert duffel.test_mode()


def _fake_ground(body):
    """Stand-in for orchestrate(): a 40-minute $20 ride for any ground leg."""
    return ({"options": [{"total_min": 40, "cost": 20.0, "legs": [
        {"mode": "ride", "line": "", "line_id": "", "path": [[0, 0], [0, 1]], "color": ""}]}]}, None, None, None, None)


def _plan(monkeypatch, search):
    monkeypatch.setattr(duffel, "search", search)
    o = geo.register("Ferry Building", 37.7955, -122.3937, elev=10)
    d = geo.register("Times Square", 40.758, -73.9855, elev=50)
    return flights.plan(o, d, date(2026, 10, 25), 9, 75, _fake_ground, "America/Los_Angeles", "America/New_York", "hustle")


def test_real_offers_become_door_to_door_options(monkeypatch):
    monkeypatch.setenv("DUFFEL_API_KEY", FAKE_KEY)
    out = _plan(monkeypatch, lambda a, b, d: (duffel.parse_offers(PAYLOAD), "live"))
    assert out["fares_source"] == "duffel_test" and "test mode" in out["fares_note"]
    fast = next(o for o in out["options"] if o["offer"]["id"] == "off_fast")
    # 40 min ground + 90 check-in + 335 flight + 25 deplane + 40 ground
    assert fast["total_min"] == 40 + 90 + 335 + 25 + 40
    assert fast["offer"]["leave_by"] == "4:50 am"   # 7:00 − 90 check-in − 40 ground and fast["offer"]["dep_local"] == "7:00 am"
    assert fast["offer"]["at_door"] == "4:40 pm" and fast["total_low"] == round(389.10 + 40)
    assert out["options"][0]["total_min"] <= out["options"][-1]["total_min"]     # Hustle: fastest first


def test_duffel_failure_falls_back_to_estimates(monkeypatch):
    monkeypatch.setenv("DUFFEL_API_KEY", FAKE_KEY)

    def boom(a, b, d):
        raise FeedError("HTTP 401: Invalid authentication")
    out = _plan(monkeypatch, boom)
    assert out["fares_source"] == "estimate" and "401" in out["fares_note"]
    assert all("offer" not in o and o["flight"]["fare_low"] > 0 for o in out["options"])


def test_no_key_uses_estimates_and_says_so(monkeypatch):
    monkeypatch.delenv("DUFFEL_API_KEY", raising=False)
    out = _plan(monkeypatch, lambda *a: pytest.fail("Duffel must not be called without a key"))
    assert out["fares_source"] == "estimate" and "Duffel API key" in out["fares_note"]


def test_api_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("DUFFEL_API_KEY", FAKE_KEY)
    monkeypatch.setattr(duffel, "search", lambda a, b, d: (duffel.parse_offers(PAYLOAD), "live"))
    monkeypatch.setattr("app.server.orchestrate", _fake_ground)
    r = app.test_client().post("/api/flights", json={"origin": "ferry_building", "date": "2026-12-01",
                                                     "destination_place": {"name": "Times Square", "lat": 40.758, "lon": -73.9855}})
    assert r.status_code == 200 and FAKE_KEY not in r.get_data(as_text=True)
    assert r.json["fares_source"] == "duffel_test" and r.json["options"][0]["offer"]["airline"] == "Duffel Airways"
