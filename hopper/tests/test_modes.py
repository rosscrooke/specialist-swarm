"""Mode rules (Hustle / Broke / Burn) and the Bar Crawl planner — offline."""
from app import bars, modes, tools
from app.server import app
from app.tools import Leg, Trip


def _trip(tid, legs):
    t = Trip(legs, "test")
    t.id = tid
    return t


def walk(mi, minutes):
    return Leg("walk", "a", "b", mi, minutes, source="t")


def ride(minutes, cost=15):
    return Leg("ride", "b", "c", 2.0, minutes, cost=cost, source="t")


def muni(minutes):
    return Leg("muni", "b", "c", 3.0, minutes, cost=2.85, line="N", source="t")


def test_hustle_drops_long_walks():
    short = _trip("short", [walk(0.3, 6), ride(10)])
    long = _trip("long", [walk(1.0, 20), ride(8)])
    kept, notice = modes.mode_filter([short, long], "hustle")
    assert [t.id for t in kept] == ["short"] and notice == ""


def test_broke_uses_ride_only_as_last_resort():
    transit = _trip("transit", [walk(0.3, 6), muni(18)])     # 24 min ≤ 2.5 × 10
    cab = _trip("cab", [ride(10)])
    kept, _ = modes.mode_filter([transit, cab], "broke")
    assert [t.id for t in kept] == ["transit"]
    kept, _ = modes.mode_filter([cab], "broke")
    assert [t.id for t in kept] == ["cab"]


def test_burn_needs_transit_and_forty_percent_active():
    hybrid = _trip("hybrid", [walk(1.5, 25), muni(25)])       # 50 min, 50% active
    lazy = _trip("lazy", [walk(0.1, 2), muni(25)])            # 27 min, 7% active
    hike = _trip("hike", [walk(2.0, 40)])                     # no transit
    kept, notice = modes.mode_filter([hybrid, lazy, hike], "burn")
    assert [t.id for t in kept] == ["hybrid"] and notice == ""


def test_burn_compares_to_fastest_transit_not_fastest_overall():
    hybrid = _trip("hybrid", [walk(1.5, 30), muni(25)])       # 55 min
    direct = _trip("direct", [muni(30)])                      # fastest transit: 30 min
    cab = _trip("cab", [ride(10)])                            # 10 min overall
    kept, _ = modes.mode_filter([hybrid, direct, cab], "burn")
    assert "hybrid" in [t.id for t in kept]                   # 55 ≤ 2 × 30


def test_empty_filter_falls_back_with_notice():
    cab = _trip("cab", [ride(10)])
    kept, notice = modes.mode_filter([cab], "burn")
    assert kept == [cab] and "Burn" in notice


BAR = {"id": "n1", "name": "Vesuvio", "type": "pub", "lat": 37.7976, "lon": -122.4066, "n_tags": 12,
       "tags": {"wikidata": "Q1", "website": "https://x", "opening_hours": "Mo-Su 08:00-02:00"}}
TIKI = {"id": "n2", "name": "Tiki Lounge", "type": "bar", "lat": 37.7990, "lon": -122.4080, "n_tags": 4,
        "tags": {"cocktails": "yes"}}
FAR = {"id": "n3", "name": "Far Bar", "type": "bar", "lat": 37.7600, "lon": -122.4300, "n_tags": 3, "tags": {}}


def test_cool_score_rewards_landmarks_and_vibe():
    assert bars.cool_score(BAR) > bars.cool_score(TIKI)
    assert bars.cool_score(TIKI, "cocktail") > bars.cool_score(TIKI, "any")
    assert bars.vibe_match(TIKI, "cocktail") and not bars.vibe_match(BAR, "cocktail")


def test_choose_stops_stays_walkable():
    best, _ = bars.choose_stops([BAR, TIKI, FAR], [37.8008, -122.4100], 2, "any", hop_mi=0.4)
    assert {b["id"] for b in best} == {"n1", "n2"}          # the far bar is never picked
    best, _ = bars.choose_stops([BAR, TIKI, FAR], [37.8008, -122.4100], 3, "any", hop_mi=0.4)
    assert best is None                                      # can't make 3 walkable stops


def test_snapshot_loads_and_has_landmarks():
    snap = bars.json.loads(bars.SNAPSHOT.read_text())
    assert len(snap["bars"]) > 400
    assert any("wikidata" in b["tags"] for b in snap["bars"])


def test_crawl_api_requires_age_confirmation():
    client = app.test_client()
    res = client.post("/api/crawl", json={"start": "washington_sq", "stops": 3})
    assert res.status_code == 403


def test_ride_fare_helper_matches_ride_leg():
    leg = tools.ride_leg("union_square", "powell", hour=12)
    assert leg.cost == tools.ride_fare(leg.distance_mi, leg.minutes, 1.0)


def test_broke_skips_slow_trips_that_barely_save():
    cab = _trip("cab", [ride(15, cost=15.93)])
    crawl = _trip("crawl", [muni(37), ride(15, cost=11.95)])    # +37 min to save $1.13
    bus = _trip("bus", [walk(0.3, 6), muni(30)])                # +21 min to save $13.08
    kept, _ = modes.mode_filter([cab, crawl], "broke")
    assert [t.id for t in kept] == ["cab"]                      # the slow combo isn't worth it
    kept, _ = modes.mode_filter([cab, crawl, bus], "broke")
    assert [t.id for t in kept] == ["bus"]
