"""Eval checks. Each takes plan output and returns a list of failure strings ([] = pass).

Checks read the planner's *response* (what the rider sees) and judge it against the spec in
cases.json — they never call the code under test to decide what's right, so a bug in the
planner can't hide by also being in the oracle.
"""
import json
import re
from pathlib import Path

from app.agents import grounded

NONSTOP = json.loads((Path(__file__).resolve().parent.parent / "app" / "fixtures" / "routes.json").read_text())["routes"]
TRANSIT = ("muni", "bart", "cable", "bus", "tram", "metro", "rail", "ferry")
ACTIVE = ("walk", "bike", "ebike")
EPS = 1e-6


def modes_of(trip):
    return [l["mode"] for l in trip["legs"]]


def active_share(trip):
    return sum(l["minutes"] for l in trip["legs"] if l["mode"] in ACTIVE) / (trip["total_min"] or 1)


def trip_dict(t):
    """A feasible Trip object → the same shape as a response option."""
    return t.to_dict() if hasattr(t, "to_dict") else t


# ── Integrity: the trip is a real, connected journey ─────────────────────────

def integrity(resp):
    fails = []
    origin, dest = resp["request"]["origin"], resp["request"]["destination"]
    if not resp["options"]:
        return ["no options returned"]
    for o in resp["options"] + [resp["baseline"]]:
        legs, tag = o["legs"], o.get("label", "baseline")
        if legs[0]["frm"] != origin or legs[-1]["to"] != dest:
            fails.append(f"{tag}: starts at {legs[0]['frm']} / ends at {legs[-1]['to']}")
        for a, b in zip(legs, legs[1:]):
            if a["to"] != b["frm"]:
                fails.append(f"{tag}: gap between legs ({a['to']} → {b['frm']})")
        for l in legs:
            if min(l["distance_mi"], l["minutes"], l["cost"], l["wait_min"]) < 0:
                fails.append(f"{tag}: negative number on a {l['mode']} leg")
    return fails


# ── Grounding + faithfulness of the one-line explanation ─────────────────────

def deltas(option, baseline):
    """Independent recomputation of the trade-offs vs. the door-to-door ride."""
    return {"saves": round(baseline["cost"] - option["cost"], 2),
            "slower_min": round(option["total_min"] - baseline["total_min"]),
            "extra_kcal": option["kcal"] - baseline["kcal"]}


CLAIMS = (
    # pattern, which delta it quotes, how the quoted number relates to that delta
    (re.compile(r"saves? \$(\d+(?:\.\d+)?)"), "saves", lambda n, d: abs(n - d) <= 0.011),
    (re.compile(r"costs? \$(\d+(?:\.\d+)?) more"), "saves", lambda n, d: abs(n + d) <= 0.011),
    (re.compile(r"(\d+) min(?:utes)? faster"), "slower_min", lambda n, d: n == -d),
    (re.compile(r"\+(\d+) min"), "slower_min", lambda n, d: n == d),
    (re.compile(r"(\d+) min(?:utes)? (?:longer|slower)"), "slower_min", lambda n, d: n == d),
    (re.compile(r"\+(\d+) kcal"), "extra_kcal", lambda n, d: n == d),
)


def explanation(resp):
    """Every number in `why` must come from the facts (grounding), and every trade-off it
    states must be true and point the right way — "saves" vs "costs more" (faithfulness)."""
    fails = []
    base = resp["baseline"]
    for o in resp["options"]:
        why, d = o.get("why") or "", deltas(o, base)
        if not why:
            fails.append(f"{o['label']}: empty explanation")
            continue
        # Same facts the Explainer is given — including whole-minute totals — minus the sentence itself.
        facts = json.dumps({"option": {k: v for k, v in o.items() if k != "why"}, "baseline": base, "deltas": d,
                            "minutes": round(o["total_min"]), "baseline_minutes": round(base["total_min"]),
                            "abs": {k: abs(v) for k, v in d.items()}}, ensure_ascii=False)
        if not grounded(why, facts):
            fails.append(f"{o['label']}: ungrounded number in “{why}”")
        for pattern, key, ok in CLAIMS:
            for m in pattern.finditer(why):
                if not ok(float(m.group(1)), d[key]):
                    fails.append(f"{o['label']}: claims “{m.group(0)}” but {key} = {d[key]}")
    return fails


# ── Label honesty: chips match the numbers ───────────────────────────────────

def labels(resp):
    fails, opts = [], resp["options"]
    for o in opts:
        lbl = o["label"]
        if "Fastest" in lbl and any(p["total_min"] < o["total_min"] - EPS for p in opts):
            fails.append(f"“{lbl}” is not the fastest option shown")
        if "Cheapest" in lbl and any(p["cost"] < o["cost"] - EPS for p in opts):
            fails.append(f"“{lbl}” is not the cheapest option shown")
        if "Healthiest" in lbl and any(p["kcal"] > o["kcal"] for p in opts):
            fails.append(f"“{lbl}” is not the most active option shown")
    return fails


# ── Mode correctness: the top pick obeys and serves its Mode ─────────────────

def complies(trip, spec, feasible):
    """Does a trip satisfy a Mode's hard rules (judged against all feasible trips)?"""
    walks = [l["distance_mi"] for l in trip["legs"] if l["mode"] == "walk"]
    if any(w > spec["max_walk_leg_mi"] + EPS for w in walks) or sum(walks) > spec["max_total_walk_mi"] + EPS:
        return False
    if spec.get("needs_transit"):
        if not any(m in TRANSIT for m in modes_of(trip)) or active_share(trip) < spec["min_active_share"] - EPS:
            return False
    if spec.get("max_slowdown_vs_fastest_transit"):
        # "Slow is fine, but not absurd": bounded by the fastest transit trip (or any trip if no transit).
        pool = [t for t in feasible if any(m in TRANSIT for m in modes_of(t))] or feasible
        if trip["total_min"] > min(t["total_min"] for t in pool) * spec["max_slowdown_vs_fastest_transit"] + EPS:
            return False
    return True


def mode_correctness(mode, resp, feasible, spec):
    feasible = [trip_dict(t) for t in feasible]
    top, notice = resp["options"][0], resp.get("notice") or ""
    ok = [t for t in feasible if complies(t, spec, feasible)]
    if not ok:
        return [] if notice else [f"no trip complies with {mode} but no notice was shown"]
    fails = []
    if notice:
        fails.append(f"notice “{notice}” shown although {len(ok)} trips comply")
    if not complies(top, spec, feasible):
        fails.append(f"top pick ({'+'.join(modes_of(top))}, {top['total_min']} min, "
                     f"{top['walk_mi']} mi walk) breaks {mode}'s rules")
    if mode == "hustle":
        best = min(t["total_min"] for t in ok)
        if top["total_min"] > best * (1 + spec["top_within_fastest_pct"] / 100) + EPS:
            fails.append(f"top pick {top['total_min']} min vs fastest compliant {best} min")
    elif mode == "broke":
        no_ride = [t for t in ok if "ride" not in modes_of(t)]
        if spec.get("ride_last_resort") and no_ride and "ride" in modes_of(top):
            fails.append(f"top pick uses a ride though {len(no_ride)} ride-free trips comply")
        per_hour = spec.get("min_saving_per_hour_usd")
        if per_hour:
            for u in ok:
                extra = top["total_min"] - u["total_min"]
                if extra > 0 and u["cost"] - top["cost"] < per_hour * extra / 60 - EPS:
                    fails.append(f"top pick is {extra:.0f} min slower than a compliant trip to save only "
                                 f"${u['cost'] - top['cost']:.2f} (needs ${per_hour * extra / 60:.2f})")
                    break
            ok = [t for t in ok if not any(u["total_min"] < t["total_min"] and
                                           u["cost"] - t["cost"] < per_hour * (t["total_min"] - u["total_min"]) / 60 - EPS
                                           for u in ok)]
            no_ride = [t for t in ok if "ride" not in modes_of(t)]
        pool = no_ride or ok
        best = min(t["cost"] for t in pool)
        if top["cost"] > best + spec["top_within_cheapest_usd"] + EPS:
            fails.append(f"top pick ${top['cost']:.2f} vs cheapest compliant ${best:.2f}")
    elif mode == "burn":
        best = max(t["kcal"] for t in ok)
        if top["kcal"] < best * (1 - spec["top_within_max_kcal_pct"] / 100) - EPS:
            fails.append(f"top pick {top['kcal']} kcal vs most active compliant {best} kcal")
    return fails


GOAL = {"hustle": ("total_min", min, "min"), "broke": ("cost", min, "$"), "burn": ("active_min", max, "active min")}


def cross_mode(tops, notices, spec, feasible):
    """Same request, different Modes: each Mode's pick must do at least as well on its own
    goal as any other Mode's pick that *also obeys this Mode's rules* — Burn's 1.6-mile walk
    to save $1.64 isn't a trip Broke was allowed to choose."""
    fails, feasible = [], [trip_dict(t) for t in feasible]
    for mode, mine in tops.items():
        if notices.get(mode):
            continue
        field, better, unit = GOAL[mode]
        for other, theirs in tops.items():
            if other == mode or not complies(theirs, spec[mode], feasible):
                continue
            if mode == "broke" and "ride" in modes_of(theirs) and "ride" not in modes_of(mine):
                continue                     # a ride-free pick wins Broke even if it costs a bit more
            per_hour = spec[mode].get("min_saving_per_hour_usd")
            if per_hour and theirs["total_min"] > mine["total_min"] and \
                    mine["cost"] - theirs["cost"] < per_hour * (theirs["total_min"] - mine["total_min"]) / 60:
                continue                     # cheaper, but too slow for what it saves
            if better(mine[field], theirs[field]) != mine[field] and abs(mine[field] - theirs[field]) > EPS:
                fails.append(f"{mode.title()} pick ({mine[field]} {unit}) loses to {other.title()}'s "
                             f"({theirs[field]} {unit}), which also obeys {mode.title()}'s rules")
    return fails


# ── Hand-written expectations for a golden case ──────────────────────────────

def expectations(case, by_mode):
    fails, exp = [], case.get("expect") or {}
    every = [o for r in by_mode.values() for o in r["options"]]
    if exp.get("no_bikes"):
        fails += [f"{o['label']} uses bike share in rain" for o in every
                  if {"bike", "ebike"} & set(modes_of(o))]
    if "max_cost" in exp:
        fails += [f"{o['label']} costs ${o['cost']:.2f} > ${exp['max_cost']}" for o in every
                  if o["cost"] > exp["max_cost"] + EPS]
    if exp.get("no_steep_walks"):
        from app.tools import STEEP_GRADE
        fails += [f"{o['label']} walks a {l['grade']:.0%} grade" for o in every for l in o["legs"]
                  if l["mode"] == "walk" and l["grade"] > STEEP_GRADE + EPS]
    broke_top = by_mode["broke"]["options"][0] if "broke" in by_mode else None
    if broke_top and exp.get("broke_top_uses"):
        missing = set(exp["broke_top_uses"]) - set(modes_of(broke_top))
        if missing:
            fails.append(f"Broke top pick ({'+'.join(modes_of(broke_top))}) doesn't use {', '.join(missing)}")
    if broke_top and exp.get("broke_top_no_ride") and "ride" in modes_of(broke_top):
        fails.append(f"Broke top pick uses a ride ({'+'.join(modes_of(broke_top))})")
    return fails


# ── Intent extraction ────────────────────────────────────────────────────────

def intent(case, parsed):
    fails = []
    for k, want in case["expect"].items():
        got = parsed.get(k)
        if k.endswith("_text") and isinstance(got, str):
            same = want.lower() in got.lower()        # "Big Ben, London" still geocodes to Big Ben
        elif isinstance(want, str) and isinstance(got, str):
            same = got.strip().lower() == want.lower()
        elif isinstance(want, (int, float)) and not isinstance(want, bool):
            same = isinstance(got, (int, float)) and abs(got - want) < EPS
        else:
            same = got == want
        if not same:
            fails.append(f"{k}: expected {want!r}, got {got!r}")
    for k in case.get("absent", []):
        if parsed.get(k) is not None:
            fails.append(f"{k}: expected none, got {parsed[k]!r}")
    return fails


# ── World trips ──────────────────────────────────────────────────────────────

def world_expectations(case, by_mode):
    fails, exp = [], case.get("expect") or {}
    for mode, r in by_mode.items():
        if r["request"]["region"] != "world":
            fails.append(f"{mode}: planned as region {r['request']['region']!r}, not world")
        if exp.get("tz") and r["request"]["tz"] != exp["tz"]:
            fails.append(f"{mode}: local time zone {r['request']['tz']}, expected {exp['tz']}")
        if exp.get("units") and r["units"] != exp["units"]:
            fails.append(f"{mode}: shows {r['units']}, expected {exp['units']}")
    every = [o for r in by_mode.values() for o in r["options"]]
    if exp.get("uses_transit") and not any(set(modes_of(o)) & set(TRANSIT) for o in every):
        fails.append("no option uses the city's transit")
    if exp.get("no_bikes"):
        fails += [f"{o['label']} uses bike share in rain" for o in every if {"bike", "ebike"} & set(modes_of(o))]
    return fails


# ── Flights (door to door) ───────────────────────────────────────────────────

def flights(case, mode, out):
    """Door-to-door totals add up, airports are near the right ends, and the Mode sets the order."""
    fails, exp, opts = [], case.get("expect") or {}, out.get("options") or []
    if not opts:
        return [f"no flight options ({out.get('error')})"]
    for o in opts:
        tag = f"{o['dep']['iata']}→{o['arr']['iata']}"
        f, g1, g2 = o["flight"], o["ground_to"], o["ground_from"]
        if not (g1["ok"] and g2["ok"]):
            fails.append(f"{tag}: ground leg failed ({g1.get('error') or g2.get('error')})")
        legs = (g1["minutes"] if g1["ok"] else 60) + f["buffer_before"] + f["minutes"] + f["buffer_after"] \
            + (g2["minutes"] if g2["ok"] else 60)
        if o["total_min"] != round(legs):
            fails.append(f"{tag}: door-to-door {o['total_min']} min ≠ parts {round(legs)} min")
        ground = (g1.get("cost") or 0) + (g2.get("cost") or 0)
        if o["total_low"] != round(f["fare_low"] + ground) or o["total_high"] != round(f["fare_high"] + ground):
            fails.append(f"{tag}: total fare doesn't equal flight fare + ground costs")
        if o["total_low"] > o["total_high"]:
            fails.append(f"{tag}: low fare above high fare")
        served = NONSTOP.get(o["dep"]["iata"], "").split()
        if f.get("stops", 0) == 0 and o["arr"]["iata"] not in served:
            fails.append(f"{tag}: estimated as nonstop, but no such route is scheduled")
        if o["dep"]["iata"] == o["arr"]["iata"]:
            fails.append(f"{tag}: departs and lands at the same airport")
        if not any(o["dep"]["iata"] in u and o["arr"]["iata"] in u for u in o["links"].values()):
            fails.append(f"{tag}: no booking link pre-filled with both airports")
    top = opts[0]
    if exp.get("dep_airports") and top["dep"]["iata"] not in exp["dep_airports"]:
        fails.append(f"top pick departs from {top['dep']['iata']}, expected one of {exp['dep_airports']}")
    if exp.get("arr_airports") and top["arr"]["iata"] not in exp["arr_airports"]:
        fails.append(f"top pick lands at {top['arr']['iata']}, expected one of {exp['arr_airports']}")
    key = (lambda o: (o["total_low"], o["total_min"])) if mode == "broke" else (lambda o: (o["total_min"], o["total_low"]))
    if [key(o) for o in opts] != sorted(key(o) for o in opts):
        fails.append(f"{mode}: options not ordered by {'price' if mode == 'broke' else 'door-to-door time'}")
    if mode == "broke" and exp.get("broke_ground_no_ride"):     # SF side: BART / Caltrain / Muni exist
        if any(l["mode"] == "ride" for l in top["ground_to"].get("legs", [])):
            fails.append(f"broke: gets to the airport by ride (“{top['ground_to'].get('summary')}”)")
    return fails


# ── Bar Crawl ────────────────────────────────────────────────────────────────

def _clock_min(s):
    h, rest = s.split(":")
    m, ampm = rest.split()
    return (int(h) % 12 + (12 if ampm == "pm" else 0)) * 60 + int(m)


def crawl(case, out, vibe_matches_nearby):
    """Right number of distinct bars, short hops, a timeline that adds up, honest totals."""
    fails, it = [], out["itinerary"]
    stops, walks, n = it["stops"], it["walks"], case["stops"]
    per_stop = case.get("minutes_per_stop", 45)
    if len(stops) != n:
        fails.append(f"{len(stops)} stops, asked for {n}")
    if len({s["osm_id"] for s in stops}) != len(stops):
        fails.append("the same bar appears twice")
    for w in walks[1:]:
        if w["distance_mi"] > out["hop_limit_mi"] + 0.05:
            fails.append(f"hop {w['frm_name']} → {w['to_name']} is {w['distance_mi']} mi (limit {out['hop_limit_mi']})")
    if case.get("weather") == "rain" and out["hop_limit_mi"] >= 0.4:
        fails.append(f"rain should shorten hops; limit is {out['hop_limit_mi']} mi")
    for s, w in zip(stops, walks):
        stay = (_clock_min(s["leave"]) - _clock_min(s["arrive"])) % 1440
        if stay != per_stop:
            fails.append(f"{s['name']}: stays {stay} min, expected {per_stop}")
    for prev, s, w in zip(stops, stops[1:], walks[1:]):
        gap = (_clock_min(s["arrive"]) - _clock_min(prev["leave"])) % 1440
        if abs(gap - w["minutes"]) > 1:
            fails.append(f"arrive {s['name']} {gap} min after leaving {prev['name']}, walk takes {w['minutes']}")
    t = it["totals"]
    if abs(t["minutes"] - (sum(w["minutes"] for w in walks) + n * per_stop)) > 0.5 * len(walks) + 0.5:
        fails.append(f"total {t['minutes']} min ≠ walks + {n} × {per_stop} min")
    if abs(t["walk_mi"] - sum(w["distance_mi"] for w in walks)) > 0.011:
        fails.append("total walk ≠ sum of walks")
    if case.get("end"):
        r = it["ride_home"]
        if not r or r["cost"] <= 0:
            fails.append("no ride home priced although an end point was set")
        elif "never drive" not in r["note"]:
            fails.append("ride home lacks the don't-drink-and-drive note")
    elif it["ride_home"]:
        fails.append("ride home added without an end point")
    if vibe_matches_nearby >= n:
        off = [s["name"] for s in stops if not s.get("_vibe_ok", True)]
        if off:
            fails.append(f"{', '.join(off)} don't match “{case['vibe']}” though {vibe_matches_nearby} nearby bars do")
    if any(not s["why"] for s in stops):
        fails.append("a stop has no reason it's cool")
    return fails
