"""The agent eval suite runs in CI, and seeded bugs prove each check can actually fail."""
import copy

from app import modes
from evals import checks, run


def _fmt(failures):
    return "\n".join(f"{r['suite']} · {r['case']}: {'; '.join(r['fails'])}" for r in failures)


def test_offline_evals_pass():
    report = run.run()
    assert report.results, "no eval results"
    assert not report.failures, _fmt(report.failures)


def test_catches_a_mode_that_drifts_from_its_spec(monkeypatch):
    # Someone loosens Hustle's walk limit in code; the spec in cases.json still says 0.4 mi.
    monkeypatch.setitem(modes.MODES, "hustle", {**modes.MODES["hustle"], "max_walk_leg_mi": 2.0,
                                                "max_total_walk_mi": 3.0, "weights": {"time": 0.5, "cost": 3.0, "health": 0.5}})
    report = run.run()
    assert any(r["suite"] == "mode" and "/hustle" in r["case"] for r in report.failures)


def _resp(why):
    leg = {"mode": "ride", "frm": "a", "to": "b", "distance_mi": 2.0, "minutes": 10, "wait_min": 0,
           "cost": 12.0, "line": "", "grade": 0}
    base = {"legs": [dict(leg, cost=15.0)], "total_min": 10, "cost": 15.0, "kcal": 0}
    opt = {"label": "Recommended", "legs": [leg], "total_min": 10, "cost": 12.0, "kcal": 0, "why": why}
    return {"request": {"origin": "a", "destination": "b"}, "options": [opt], "baseline": base}


def test_explanation_checks():
    assert checks.explanation(_resp("Ride 2 mi to b. saves $3.00 vs. a door-to-door ride.")) == []
    # Right number, wrong direction — grounding alone can't catch this; faithfulness does.
    assert "claims" in checks.explanation(_resp("Ride 2 mi to b; costs $3.00 more."))[0]
    # A number that appears nowhere in the facts.
    assert "ungrounded" in checks.explanation(_resp("Ride 2 mi to b, saves 40% on the fare."))[0]


def test_grounding_compares_values_not_digits():
    from app.agents import grounded
    assert grounded("saves $3.00", '{"saves": 3.0}')
    assert not grounded("+100 kcal", '{"kcal": 1}')       # "100" used to strip to "1"
    assert not grounded("40% off", '{"x": 4}')


def test_label_honesty():
    resp = _resp("x")
    slow = copy.deepcopy(resp["options"][0])
    slow.update(label="Fastest", total_min=20)
    resp["options"].append(slow)
    assert checks.labels(resp) == ["“Fastest” is not the fastest option shown"]


def test_golden_drift_is_reported():
    want = {"legs": "walk+muni:N", "total_min": 30, "cost": 2.85, "kcal": 100}
    assert run.golden_diff(want, dict(want, total_min=31)) == []          # within 10 %
    fails = run.golden_diff(want, {"legs": "ride", "total_min": 15, "cost": 18.0, "kcal": 0})
    assert len(fails) == 4


def test_intent_check_is_case_insensitive_and_checks_absent_fields():
    case = {"expect": {"origin_text": "500 Folsom St", "max_cost": 5}, "absent": ["origin"]}
    assert checks.intent(case, {"origin_text": "500 folsom st", "max_cost": 5.0}) == []
    assert len(checks.intent(case, {"origin": "moscone", "max_cost": 6})) == 3


class _FakeClaude:
    """Stands in for Anthropic: answers the trip_request tool with a fixed guess."""
    def __init__(self, guess):
        from types import SimpleNamespace as NS
        block = NS(type="tool_use", input=guess)
        self.messages = NS(create=lambda **kw: NS(content=[block], usage=NS(input_tokens=1, output_tokens=1)))


def test_curated_alias_beats_claudes_guess():
    from app import agents
    trace = agents.Trace()
    claude = _FakeClaude({"origin": "golden_gate_park", "destination": "ferry_building", "mode": "hustle"})
    parsed = agents.intent_agent("from ggp to fidi, I'm late", trace, claude)
    assert parsed["destination"] == "montgomery" and parsed["mode"] == "hustle"
    assert "kept destination=montgomery" in trace.steps[-1]["detail"]


def test_claude_still_wins_without_an_alias():
    from app import agents
    # "the big ferry place" has no alias, so Claude's reading stands.
    claude = _FakeClaude({"origin": "coit_tower", "destination": "ferry_building"})
    parsed = agents.intent_agent("from coit tower to the big ferry place", agents.Trace(), claude)
    assert parsed["destination"] == "ferry_building"
    # Addresses never trigger an alias, even when a word looks like one ("Dolores St").
    assert agents.alias_place("500 Dolores St") is None and agents.alias_place("fidi") == "montgomery"


def test_broke_slowdown_is_measured_against_transit():
    from tests.test_modes import _trip, muni, ride, walk
    from app.tools import Leg
    ebike = _trip("ebike", [Leg("ebike", "a", "c", 3.0, 14, cost=11.59, source="t")])
    bus = _trip("bus", [walk(0.3, 6), muni(30)])            # 36 min: 2.6× the e-bike, 1× fastest transit
    kept, notice = modes.mode_filter([ebike, bus], "broke")
    assert "bus" in [t.id for t in kept] and notice == ""


def test_replay_misses_fail_like_an_outage():
    import pytest
    from app import world
    from app.live import FeedError
    from evals import replay
    with replay.cassette([]):
        with pytest.raises(FeedError, match="not in eval cassette"):
            world.get_json("https://api.transitous.org/api/v1/plan", {"fromPlace": "0,0"})


def test_flight_and_crawl_checks_catch_bad_arithmetic():
    g = {"ok": True, "minutes": 30, "cost": 2.4, "legs": [], "summary": "BART"}
    f = {"buffer_before": 90, "minutes": 60, "buffer_after": 30, "fare_low": 100, "fare_high": 200}
    o = {"dep": {"iata": "SFO"}, "arr": {"iata": "LAX"}, "flight": f, "ground_to": g, "ground_from": g,
         "total_min": 240, "total_low": 105, "total_high": 205, "links": {"g": "SFO-LAX"}}
    assert checks.flights({}, "hustle", {"options": [o]}) == []
    assert "≠ parts" in checks.flights({}, "hustle", {"options": [dict(o, total_min=200)]})[0]
    stop = {"name": "Bar", "osm_id": 1, "arrive": "8:10 pm", "leave": "8:56 pm", "why": "x"}
    walk = {"distance_mi": 0.2, "minutes": 10, "frm_name": "a", "to_name": "Bar"}
    out = {"hop_limit_mi": 0.5, "itinerary": {"stops": [stop], "walks": [walk], "ride_home": None,
                                              "totals": {"minutes": 55, "walk_mi": 0.2}}}
    assert "stays 46 min" in checks.crawl({"stops": 1}, out, 0)[0]
