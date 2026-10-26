"""Ride types for the ride chooser: fares, pickup ETAs, availability — all SIMULATED.

Uber and Lyft don't offer public price APIs, so Hopper estimates each ride type with a
transparent fare model and shows "Open in Uber" / "Open in Lyft" deep links (their public
universal links, pickup and drop-off prefilled) for real quotes. Generic tier names on
purpose: nothing here pretends to be a real company's product or price.
"""
import hashlib
from urllib.parse import urlencode

from .data import RIDE

TIERS = [
    # id, name, blurb, seats, price multiplier, min fare, extra ETA (min), extra ride time (min)
    {"id": "go", "name": "Go", "blurb": "Everyday rides", "seats": 4, "mult": 1.00, "min": 9.0, "eta": 0, "detour": 0},
    {"id": "shared", "name": "Shared", "blurb": "Share the ride, pay less", "seats": 2, "mult": 0.72, "min": 7.0, "eta": 1, "detour": 7},
    {"id": "green", "name": "Green", "blurb": "Electric and hybrid cars", "seats": 4, "mult": 1.06, "min": 9.5, "eta": 2, "detour": 0},
    {"id": "comfort", "name": "Comfort", "blurb": "Newer cars, extra legroom", "seats": 4, "mult": 1.32, "min": 12.0, "eta": 1, "detour": 0},
    {"id": "xl", "name": "XL", "blurb": "Up to 6 riders", "seats": 6, "mult": 1.62, "min": 14.0, "eta": 3, "detour": 0},
    {"id": "premium", "name": "Premium", "blurb": "Top-rated drivers, luxury cars", "seats": 4, "mult": 2.25, "min": 25.0, "eta": 5, "detour": 0},
    {"id": "taxi", "name": "Taxi", "blurb": "Metered fare, no surge", "seats": 4, "mult": None, "min": 0.0, "eta": 2, "detour": 0},
]
TAXI = {"flag": 3.50, "per_mile": 2.75, "per_min": 0.55}     # typical big-US-city meter
RANGE = 0.09                                                 # ± shown as a fare range


def _hash(*parts):
    return int(hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest(), 16)


def pickup_eta(lat, lon, hour, tier):
    """Deterministic pseudo-ETA (minutes) — repeatable for demos and tests."""
    cell = (round(lat, 2), round(lon, 2))
    base = 2 + _hash(cell, hour, tier["id"]) % 6
    late = 3 if hour >= 23 or hour < 5 else 0
    return base + tier["eta"] + late


def availability(tier, hour, surge, lat, lon):
    """(available, reason). Shared pauses late at night and in heavy surge; Premium is
    sometimes fully booked (deterministic per area and hour)."""
    if tier["id"] == "shared" and (hour >= 22 or hour < 6):
        return False, "Not offered late at night"
    if tier["id"] == "shared" and surge >= 1.5:
        return False, "Paused while demand is high"
    if tier["id"] == "premium" and _hash(round(lat, 2), round(lon, 2), hour, "premium") % 7 == 0:
        return False, "No cars nearby right now"
    return True, ""


def fare(tier, dist_mi, minutes, surge):
    if tier["id"] == "taxi":
        return round(TAXI["flag"] + TAXI["per_mile"] * dist_mi + TAXI["per_min"] * minutes * 0.25, 2)
    base = (RIDE["base"] + RIDE["per_mile"] * dist_mi + RIDE["per_min"] * minutes) * tier["mult"] * surge
    return round(max(base, tier["min"]) + RIDE["booking_fee"], 2)


def deep_links(pickup, dropoff):
    """Public universal links that open the real apps with the trip filled in."""
    uber = "https://m.uber.com/ul/?" + urlencode({
        "action": "setPickup",
        "pickup[latitude]": pickup["lat"], "pickup[longitude]": pickup["lon"], "pickup[nickname]": pickup["name"],
        "dropoff[latitude]": dropoff["lat"], "dropoff[longitude]": dropoff["lon"], "dropoff[nickname]": dropoff["name"]})
    lyft = "https://lyft.com/ride?" + urlencode({
        "id": "lyft", "pickup[latitude]": pickup["lat"], "pickup[longitude]": pickup["lon"],
        "destination[latitude]": dropoff["lat"], "destination[longitude]": dropoff["lon"]})
    return {"uber": uber, "lyft": lyft}


def options(pickup, dropoff, dist_mi, minutes, hour, surge=1.0, now_min=None):
    """All ride types for one ride leg, cheapest available first.
    `now_min` = minutes after local midnight at departure (for drop-off times)."""
    out = []
    for t in TIERS:
        ok, why = availability(t, hour, surge, pickup["lat"], pickup["lon"])
        eta = pickup_eta(pickup["lat"], pickup["lon"], hour, t)
        price = fare(t, dist_mi, minutes, 1.0 if t["id"] == "taxi" else surge)
        ride_min = minutes + t["detour"]
        out.append({
            "id": t["id"], "name": t["name"], "blurb": t["blurb"], "seats": t["seats"],
            "available": ok, "reason": why, "eta_min": eta, "ride_min": round(ride_min),
            "price": price, "price_low": round(price * (1 - RANGE), 2), "price_high": round(price * (1 + RANGE), 2),
            "surge": surge if t["id"] != "taxi" else 1.0, "metered": t["id"] == "taxi",
            "dropoff_min": None if now_min is None else round(now_min + eta + ride_min),
        })
    out.sort(key=lambda o: (not o["available"], o["price"]))
    return out


def for_leg(leg_dict, hour, now_min=None):
    """Ride options for a planned ride leg (as serialised by Trip.to_dict)."""
    p = leg_dict["path"][0]
    d = leg_dict["path"][-1]
    pickup = {"name": leg_dict.get("frm_name") or "Pickup", "lat": p[0], "lon": p[1]}
    dropoff = {"name": leg_dict.get("to_name") or "Drop-off", "lat": d[0], "lon": d[1]}
    return {"options": options(pickup, dropoff, float(leg_dict["distance_mi"]), float(leg_dict["minutes"]),
                               hour, float(leg_dict.get("surge") or 1.0), now_min),
            "links": deep_links(pickup, dropoff), "pickup": pickup, "dropoff": dropoff}


def simulated_note():
    return ("Ride types, prices and pickup times are simulated estimates. "
            "Open Uber or Lyft for real quotes.")

