"""Rider Modes: presets of ranking weights + hard rules applied on top of the Critic.

Hustle / Broke / Burn re-rank the same feasible trips; Bar Crawl is a different planner
(see bars.py). `mode_filter` is pure and runs again on every mode switch, so the plan's
cached trips must be planned with the loosest walk limits (see LOOSEST_*).
"""

TRIP_MODES = ("hustle", "broke", "burn")

MODES = {
    "hustle": {"label": "Hustle", "goal": "fastest",
               "weights": {"time": 3.0, "cost": 0.5, "health": 0.0},
               "max_walk_leg_mi": 0.4, "max_total_walk_mi": 0.8},
    "broke": {"label": "Broke", "goal": "budget",
              "weights": {"time": 0.5, "cost": 3.0, "health": 0.0},   # budget first: no paying extra for calories
              "max_walk_leg_mi": 1.5, "max_total_walk_mi": 2.5,
              "max_slowdown": 2.5, "slowdown_vs": "transit", "ride_last_resort": True,
              "min_saving_per_hour": 3.0},     # a slower trip must save ≥ $1 per 20 extra minutes
    "burn": {"label": "Burn", "goal": "part transit / part workout",
             "weights": {"time": 0.5, "cost": 0.5, "health": 3.0},
             "max_walk_leg_mi": 2.0, "max_total_walk_mi": 3.0,
             "max_slowdown": 2.0, "slowdown_vs": "transit", "needs_transit": True, "min_active_share": 0.4},
    "barcrawl": {"label": "Bar Crawl", "goal": "hit cool bars"},
}

LOOSEST_WALK_LEG_MI = max(m.get("max_walk_leg_mi", 0) for m in MODES.values())
LOOSEST_TOTAL_WALK_MI = max(m.get("max_total_walk_mi", 0) for m in MODES.values())

TRANSIT = ("muni", "bart", "cable", "bus", "tram", "metro", "rail", "ferry")
ACTIVE = ("walk", "bike", "ebike")


def active_share(trip):
    total = trip.total_min or 1
    return sum(l.minutes for l in trip.legs if l.mode in ACTIVE) / total


def worth_the_wait(trip, others, per_hour):
    """False when some faster trip costs barely more: +37 min to save $1.13 isn't a deal.
    The fastest trip always passes, so this never empties the list."""
    return all(u.cost - trip.cost >= per_hour * (trip.total_min - u.total_min) / 60 - 1e-9
               for u in others if u.total_min < trip.total_min)


def mode_filter(trips, mode, caps=None):
    """Apply a Mode's hard rules. Returns (kept, notice). When nothing passes, returns the
    input unchanged with a notice so the rider still sees options."""
    m = MODES.get(mode)
    if not m or mode not in TRIP_MODES or not trips:
        return trips, ""
    caps = caps or {}
    leg_cap = min(m["max_walk_leg_mi"], caps.get("max_walk_leg_mi", m["max_walk_leg_mi"]))
    total_cap = min(m["max_total_walk_mi"], caps.get("max_total_walk_mi", m["max_total_walk_mi"]))
    kept = [t for t in trips
            if all(l.distance_mi <= leg_cap + 1e-9 for l in t.legs if l.mode == "walk")
            and t.walk_mi <= total_cap + 1e-9]
    if m.get("needs_transit"):
        kept = [t for t in kept if any(l.mode in TRANSIT for l in t.legs)
                and active_share(t) >= m["min_active_share"]]
    if kept and m.get("max_slowdown"):
        # Broke and Burn are measured against the fastest transit option, not an e-bike or a
        # car: "2.5× a 14-min e-bike" would rule out every $2.85 bus and leave Broke an $11 e-bike.
        pool = [t for t in trips if any(l.mode in TRANSIT for l in t.legs)] \
            if m.get("slowdown_vs") == "transit" else trips
        fastest = min(t.total_min for t in (pool or trips))
        kept = [t for t in kept if t.total_min <= fastest * m["max_slowdown"]]
    if kept and m.get("min_saving_per_hour"):
        kept = [t for t in kept if worth_the_wait(t, kept, m["min_saving_per_hour"])]
    if kept and m.get("ride_last_resort"):
        no_ride = [t for t in kept if not any(l.mode == "ride" for l in t.legs)]
        kept = no_ride or kept
    if not kept:
        rules = {"hustle": f"walks ≤ {leg_cap} mi", "broke": "within 2.5× the fastest transit trip",
                 "burn": "a transit leg + ≥ 40% active time, within 2× the fastest transit trip"}[mode]
        return trips, f"No trip met {m['label']}'s rules ({rules}) — showing the closest options."
    return kept, ""
