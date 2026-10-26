import pytest

from app import tools
from app.tools import Leg, Trip


def test_flat_mile_walk_burns_roughly_sixty_active_kcal():
    minutes = 1609 / 1000 / tools.tobler_speed_kmh(0) * 60
    kcal = tools.walk_kcal(1609, minutes, 0, 80)
    assert 55 <= kcal <= 75


def test_uphill_walk_is_slower_and_burns_more():
    assert tools.tobler_speed_kmh(0.08) < tools.tobler_speed_kmh(0)
    flat = tools.walk_kcal(1000, 12, 0, 75)
    hill = tools.walk_kcal(1000, 12, 0.08, 75)
    assert hill > flat * 1.5


def test_coit_tower_walk_from_ferry_building_climbs():
    leg = tools.walk_leg("ferry_building", "coit_tower")
    assert leg.climb_ft == 265
    assert leg.grade > 0.04


def test_ride_min_fare_and_booking_fee():
    leg = tools.ride_leg("union_square", "powell", hour=12)
    assert leg.cost == pytest.approx(9.00 + 2.95)


def test_game_day_surge_only_near_stadium_in_evening():
    surged = tools.ride_leg("oracle_park", "civic_center", hour=18, event=True)
    calm = tools.ride_leg("oracle_park", "civic_center", hour=18, event=False)
    morning = tools.ride_leg("oracle_park", "civic_center", hour=10, event=True)
    assert surged.surge == 1.9 and calm.surge == 1.0 and morning.surge == 1.0
    assert surged.cost > calm.cost


def test_bart_to_sfo_charges_airport_fare():
    line = next(l for l in tools.TRANSIT_LINES if l["id"] == "BART")
    assert tools.transit_leg(line, "powell", "sfo").cost == 10.95
    assert tools.transit_leg(line, "powell", "mission_24th").cost == 2.40


def test_transit_leg_works_in_reverse_direction():
    line = next(l for l in tools.TRANSIT_LINES if l["id"] == "N")
    fwd = tools.transit_leg(line, "powell", "ocean_beach")
    back = tools.transit_leg(line, "ocean_beach", "powell")
    assert fwd.minutes == back.minutes
    assert back.path[0] == tools.latlon("ocean_beach")


def _trip(tid, minutes, cost, kcal):
    t = Trip([Leg("walk", "a", "b", 0.1, minutes, cost=cost, kcal=kcal, source="t")], "test")
    t.id = tid
    return t


def test_pareto_drops_dominated_trip():
    good = _trip("good", 10, 5, 100)
    worse = _trip("worse", 12, 6, 80)          # slower, pricier, fewer kcal
    tradeoff = _trip("fast", 5, 20, 0)
    front = tools.pareto_front([good, worse, tradeoff])
    assert {t.id for t in front} == {"good", "fast"}


def test_pick_options_returns_distinct_labelled_trips():
    trips = [_trip("fast", 5, 20, 0), _trip("cheap", 30, 0, 120), _trip("mid", 15, 6, 60)]
    picks, _, _ = tools.pick_options(trips, {"time": 1, "cost": 1, "health": 1})
    ids = [t.id for t, _ in picks]
    assert len(ids) == len(set(ids)) == 3
    assert picks[0][1].startswith("Recommended")


def test_validate_rejects_long_walk_and_disconnected_legs():
    req = {"origin": "a", "destination": "c", "max_walk_leg_mi": 1.0,
           "max_total_walk_mi": 2.0, "avoid_steep": False, "max_cost": None}
    trip = Trip([Leg("walk", "a", "b", 1.5, 30, source="t"),
                 Leg("ride", "x", "c", 1.0, 5, source="t")], "test")
    reasons = tools.validate_trip(trip, req)
    assert any("limit" in r for r in reasons)
    assert any("don't connect" in r for r in reasons)
