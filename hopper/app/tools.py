"""Deterministic tools. Every number the app shows comes from here — agents never
compute fares, minutes, or calories themselves."""
import hashlib
import math
from dataclasses import asdict, dataclass, field

from .data import (BIKE, BIKE_DOCKS, FARES, PLACES, RIDE, SF_BOUNDS, SF_EXCEPTIONS,
                   SURGE_ZONES, TRANSIT_LINES)

WALK_CIRCUITY = 1.25     # street-grid distance / straight-line distance
DRIVE_CIRCUITY = 1.30
STEP_LENGTH_M = 0.762
STEEP_GRADE = 0.04       # average uphill grade over a whole leg (real blocks are steeper)
FT_TO_M = 0.3048
MI_TO_M = 1609.34


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Leg:
    mode: str                 # walk | ride | muni | bart | cable | bike | ebike
    frm: str
    to: str
    distance_mi: float
    minutes: float            # moving time
    wait_min: float = 0.0
    cost: float = 0.0
    kcal: float = 0.0
    steps: int = 0
    climb_ft: float = 0.0
    grade: float = 0.0
    line: str = ""
    line_id: str = ""
    surge: float = 1.0
    note: str = ""            # e.g. "next N in 4 min (511 live)"
    color: str = ""           # agency line colour when known (e.g. Paris Metro 1 = #FFCD00)
    path: list = field(default_factory=list)
    source: str = ""          # which tool produced the numbers (Critic checks this)


@dataclass
class Trip:
    legs: list
    specialist: str
    id: str = ""
    flags: list = field(default_factory=list)

    @property
    def total_min(self):
        return round(sum(l.minutes + l.wait_min for l in self.legs), 1)

    @property
    def cost(self):
        return round(sum(l.cost for l in self.legs), 2)

    @property
    def kcal(self):
        return round(sum(l.kcal for l in self.legs))

    @property
    def steps(self):
        return sum(l.steps for l in self.legs)

    @property
    def walk_mi(self):
        return round(sum(l.distance_mi for l in self.legs if l.mode == "walk"), 2)

    @property
    def active_min(self):
        return round(sum(l.minutes for l in self.legs if l.mode in ("walk", "bike", "ebike")))

    @property
    def climb_ft(self):
        return round(sum(l.climb_ft for l in self.legs if l.mode in ("walk", "bike", "ebike")))

    @property
    def signature(self):
        return "|".join(f"{l.mode}:{l.frm}>{l.to}:{l.line}" for l in self.legs)

    def to_dict(self):
        return {"id": self.id, "specialist": self.specialist, "flags": self.flags,
                "total_min": self.total_min, "cost": self.cost, "kcal": self.kcal,
                "steps": self.steps, "walk_mi": self.walk_mi, "active_min": self.active_min,
                "climb_ft": self.climb_ft,
                "legs": [{**asdict(l), "frm_name": name(l.frm), "to_name": name(l.to)}
                         for l in self.legs]}


# ── Geometry ──────────────────────────────────────────────────────────────────

def name(key):
    return PLACES[key][0]


def latlon(key):
    _, lat, lon, _ = PLACES[key]
    return [lat, lon]


def elev_ft(key):
    return PLACES[key][3]


def haversine_mi(a, b):
    return haversine_pts(latlon(a), latlon(b))


def haversine_pts(p, q):
    """Great-circle miles between two [lat, lon] points."""
    (lat1, lon1), (lat2, lon2) = p, q
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def in_sf(key):
    if key in SF_EXCEPTIONS or key.startswith("geo:"):   # geo places are checked at registration
        return True
    lat, lon = latlon(key)
    return SF_BOUNDS["lat"][0] <= lat <= SF_BOUNDS["lat"][1] and \
        SF_BOUNDS["lon"][0] <= lon <= SF_BOUNDS["lon"][1]


def climb(a, b):
    """Elevation gain a → b in feet; 0 when either end's elevation isn't known yet."""
    ea, eb = elev_ft(a), elev_ft(b)
    return 0 if ea is None or eb is None else eb - ea


def leg_grade(a, b, distance_mi):
    if distance_mi <= 0:
        return 0.0
    return climb(a, b) * FT_TO_M / (distance_mi * MI_TO_M)


# ── Health math ───────────────────────────────────────────────────────────────

def tobler_speed_kmh(grade):
    """Tobler's hiking function: ~5 km/h on flat, slower uphill and on steep descents."""
    return 6 * math.exp(-3.5 * abs(grade + 0.05))


def walk_kcal(meters, minutes, grade, weight_kg):
    """Net (active) kcal via the ACSM walking equation; resting 3.5 ml/kg/min excluded."""
    if minutes <= 0:
        return 0.0
    speed = meters / minutes                          # m/min
    vo2 = 0.1 * speed + 1.8 * speed * max(grade, 0)   # ml/kg/min above rest
    return vo2 * weight_kg / 1000 * 5 * minutes        # ~5 kcal per litre O2


def bike_kcal(minutes, ebike, grade, weight_kg):
    met = 4.0 if ebike else 6.8
    met += 0 if ebike else 8 * max(grade, 0) * 10     # classic bikes feel the hills
    return (met - 1) * weight_kg * minutes / 60


# ── Leg tools (one per specialist) ────────────────────────────────────────────

def walk_leg(a, b, weight_kg=75, dist=None, path=None, source="walk_leg"):
    dist = dist if dist is not None else haversine_mi(a, b) * WALK_CIRCUITY
    g = leg_grade(a, b, dist)
    minutes = dist * MI_TO_M / 1000 / tobler_speed_kmh(g) * 60
    meters = dist * MI_TO_M
    return Leg("walk", a, b, round(dist, 2), round(minutes, 1),
               kcal=round(walk_kcal(meters, minutes, g, weight_kg), 1),
               steps=round(meters / STEP_LENGTH_M), climb_ft=max(climb(a, b), 0),
               grade=round(g, 3), path=path or [latlon(a), latlon(b)], source=source)


def surge_at(key, hour, event):
    return surge_at_point(latlon(key), hour, event)


def surge_at_point(point, hour, event):
    mult, zone = 1.0, ""
    for center, radius, m, hours, needs_event in SURGE_ZONES:
        if hour in hours and (event or not needs_event) and \
                haversine_pts(point, latlon(center)) <= radius:
            if m > mult:
                mult, zone = m, center
    return mult, zone


def ride_fare(dist, minutes, mult):
    """SIMULATED fare: base + distance + time, × surge, floored at the minimum, + booking fee."""
    fare = RIDE["base"] + RIDE["per_mile"] * dist + RIDE["per_min"] * minutes
    return round(max(fare * mult, RIDE["min_fare"]) + RIDE["booking_fee"], 2)


def drive_minutes(dist_mi, hour):
    rush = hour in range(7, 10) or hour in range(16, 19)
    mph = 30 if dist_mi > 5 else (8 if rush else 11)
    return dist_mi / mph * 60


def traffic_factor(hour):
    """OSRM car times are free-flow; SF streets aren't."""
    return 1.8 if hour in range(7, 10) or hour in range(16, 19) else 1.35


def ride_leg(a, b, hour=12, event=False, dist=None, free_flow_min=None, path=None,
             source="ride_estimate(simulated)"):
    """SIMULATED ride-hail estimate: base + distance + time + fee, × pickup-zone surge.
    Pass `dist` / `free_flow_min` / `path` from a real road route to replace the estimates."""
    dist = dist if dist is not None else haversine_mi(a, b) * DRIVE_CIRCUITY
    minutes = free_flow_min * traffic_factor(hour) if free_flow_min is not None \
        else drive_minutes(dist, hour)
    mult, _ = surge_at(a, hour, event)
    wait = RIDE["pickup_wait_min"] + (3 if mult > 1 else 0)
    return Leg("ride", a, b, round(dist, 2), round(minutes, 1), wait_min=wait,
               cost=ride_fare(dist, minutes, mult), surge=mult, path=path or [latlon(a), latlon(b)],
               source=source)


def transit_fare(line, a, b):
    if line["mode"] == "bart":
        return FARES["bart_sfo"] if "sfo" in (a, b) else FARES["bart_city"]
    return FARES[line["mode"]]


def transit_leg(line, a, b):
    stops = line["stops"]
    i, j = stops.index(a), stops.index(b)
    lo, hi = min(i, j), max(i, j)
    minutes = sum(line["seg_min"][lo:hi])
    path_keys = stops[lo:hi + 1] if i < j else list(reversed(stops[lo:hi + 1]))
    dist = sum(haversine_mi(path_keys[k], path_keys[k + 1]) for k in range(len(path_keys) - 1))
    return Leg(line["mode"], a, b, round(dist * 1.15, 2), minutes,
               wait_min=line["headway"] / 2, cost=transit_fare(line, a, b), line=line["name"],
               line_id=line["id"], path=[latlon(k) for k in path_keys],
               source="transit_route(schedule)", note=f"~{line['headway'] // 2} min avg wait (schedule)")


def dock_status(key, hour):
    """Deterministic pseudo-availability so demos and evals are reproducible."""
    h = int(hashlib.sha256(f"{key}:{hour}".encode()).hexdigest(), 16)
    return {"classic": h % 9, "ebike": (h // 9) % 5, "open_docks": (h // 45) % 12}


def bike_leg(a, b, ebike, hour=12, weight_kg=75, dist=None, path=None, source="bike_route"):
    dist = dist if dist is not None else haversine_mi(a, b) * WALK_CIRCUITY
    g = leg_grade(a, b, dist)
    mph = 13 if ebike else 10 * max(0.5, 1 - 6 * max(g, 0))
    minutes = dist / mph * 60
    extra = max(0, minutes - BIKE["included_min"])
    cost = BIKE["unlock"] + (BIKE["ebike_per_min"] * minutes if ebike
                             else math.ceil(extra / 15) * BIKE["classic_extra_per_15"])
    return Leg("ebike" if ebike else "bike", a, b, round(dist, 2), round(minutes, 1),
               wait_min=1, cost=round(cost, 2),
               kcal=round(bike_kcal(minutes, ebike, g, weight_kg), 1),
               climb_ft=max(climb(a, b), 0), grade=round(g, 3),
               path=path or [latlon(a), latlon(b)], source=source)


def nearest(key, candidates, max_mi=None):
    ranked = sorted((haversine_mi(key, c), c) for c in candidates)
    return [c for d, c in ranked if max_mi is None or d <= max_mi]


# ── Critic + Ranker tools ─────────────────────────────────────────────────────

def validate_trip(trip, req):
    """Return a list of reasons the trip is infeasible (empty list = valid)."""
    reasons = []
    for prev, nxt in zip(trip.legs, trip.legs[1:]):
        if prev.to != nxt.frm:
            reasons.append(f"legs don't connect ({prev.to} → {nxt.frm})")
    for l in trip.legs:
        if not l.source:
            reasons.append(f"{l.mode} leg has numbers not backed by a tool")
        if l.mode == "walk" and l.distance_mi > req["max_walk_leg_mi"] + 1e-9:
            reasons.append(f"walk leg {l.distance_mi} mi > limit {req['max_walk_leg_mi']} mi")
        if l.mode == "walk" and req.get("avoid_steep") and l.grade > STEEP_GRADE:
            reasons.append(f"steep uphill walk ({l.grade:.0%}) to {name(l.to)}")
    if trip.walk_mi > req["max_total_walk_mi"] + 1e-9:
        reasons.append(f"total walk {trip.walk_mi} mi > limit {req['max_total_walk_mi']} mi")
    if req.get("max_cost") is not None and trip.cost > req["max_cost"]:
        reasons.append(f"${trip.cost} over budget ${req['max_cost']}")
    if trip.legs[0].frm != req["origin"] or trip.legs[-1].to != req["destination"]:
        reasons.append("trip doesn't start/end at the requested places")
    return reasons


def pareto_front(trips):
    """Non-dominated trips on (min time, min cost, max kcal)."""
    def dominates(a, b):
        no_worse = a.total_min <= b.total_min and a.cost <= b.cost and a.kcal >= b.kcal
        better = a.total_min < b.total_min or a.cost < b.cost or a.kcal > b.kcal
        return no_worse and better
    return [t for t in trips if not any(dominates(o, t) for o in trips if o is not t)]


def score_trips(trips, weights):
    """Weighted, range-normalised score per trip (lower is better)."""
    total = sum(weights.values()) or 1
    w = {k: v / total for k, v in weights.items()}

    def norm(vals, v):
        lo, hi = min(vals), max(vals)
        return 0.0 if hi == lo else (v - lo) / (hi - lo)

    times, costs, kcals = [t.total_min for t in trips], [t.cost for t in trips], \
        [t.kcal for t in trips]
    return {t.id: w["time"] * norm(times, t.total_min) + w["cost"] * norm(costs, t.cost)
            + w["health"] * (1 - norm(kcals, t.kcal)) for t in trips}


def pick_options(trips, weights, k=3):
    """Recommended (best weighted score) + fastest / cheapest / healthiest, deduped."""
    front = pareto_front(trips)
    scores = score_trips(front, weights)
    by_score = sorted(front, key=lambda t: scores[t.id])
    picks = [(by_score[0], "Recommended")]
    extremes = {"time": ("Fastest", min(front, key=lambda t: (t.total_min, t.cost))),
                "cost": ("Cheapest", min(front, key=lambda t: (t.cost, t.total_min))),
                "health": ("Healthiest", max(front, key=lambda t: (t.kcal, -t.total_min)))}
    # Merge labels onto trips already picked, then fill slots with the extremes the
    # rider weighted LEAST — those are the trade-offs worth showing next to the pick.
    for label, best in extremes.values():
        for i, (p, lbl) in enumerate(picks):
            if p is best:
                picks[i] = (p, f"{lbl} · {label}")
    for key in sorted(extremes, key=lambda k: weights.get(k, 0)):
        label, best = extremes[key]
        if len(picks) < k and all(best is not p for p, _ in picks):
            picks.append((best, label))
    for t in by_score:
        if len(picks) >= k:
            break
        if all(t is not p for p, _ in picks):
            picks.append((t, "Balanced"))
    return picks[:k], front, scores
