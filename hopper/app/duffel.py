"""Real flight offers from the Duffel API (https://duffel.com/docs/api).

- Key: DUFFEL_API_KEY from the environment / hopper/.env — never logged, cached by, or sent
  to the browser. `duffel_test_…` keys return Duffel's sandbox airline ("Duffel Airways"),
  which the UI labels as test data.
- One offer request per airport pair (one-way, 1 adult, economy, ≤ 1 connection), with
  return_offers=true; results cached 10 minutes per pair + date.
- Offers expire (Duffel sets expires_at, usually ~30 min). Booking needs passenger details
  and payment, which this prototype doesn't collect.
"""
import os
import re

from .live import FeedError, post_json

API = "https://api.duffel.com/air/offer_requests"
VERSION = "v2"
CACHE_S = 600


def api_key():
    return (os.environ.get("DUFFEL_API_KEY") or "").strip()


def enabled():
    return bool(api_key())


def test_mode():
    return api_key().startswith("duffel_test_")


def iso_minutes(duration):
    """'PT5H30M' / 'P1DT2H' → minutes."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", duration or "")
    if not m:
        return None
    d, h, mi = (int(x or 0) for x in m.groups())
    return d * 1440 + h * 60 + mi


def parse_offers(payload, limit=6):
    """Duffel offer request response → compact offers, cheapest first."""
    offers = []
    for o in ((payload or {}).get("data") or {}).get("offers", []):
        try:
            sl = o["slices"][0]
            segs = sl["segments"]
            first, last = segs[0], segs[-1]
            duration = iso_minutes(sl.get("duration"))
            owner = o.get("owner") or {}
            flight_nos = [f"{(s.get('marketing_carrier') or {}).get('iata_code', '')} "
                          f"{s.get('marketing_carrier_flight_number', '')}".strip() for s in segs]
            offers.append({
                "id": o["id"], "source": "duffel",
                "airline": owner.get("name") or (first.get("marketing_carrier") or {}).get("name") or "Airline",
                "airline_code": owner.get("iata_code") or "",
                "logo": owner.get("logo_symbol_url") or "",
                "flight_numbers": flight_nos,
                "origin": (first.get("origin") or {}).get("iata_code"),
                "destination": (last.get("destination") or {}).get("iata_code"),
                "departing_at": first["departing_at"], "arriving_at": last["arriving_at"],   # airport-local
                "duration_min": duration, "stops": len(segs) - 1,
                "via": [(s.get("destination") or {}).get("iata_code") for s in segs[:-1]],
                "price": float(o["total_amount"]), "currency": o["total_currency"],
                "expires_at": o.get("expires_at"), "cabin": "economy",
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    offers.sort(key=lambda x: (x["price"], x["duration_min"] or 9999))
    return offers[:limit]


def search(origin_iata, dest_iata, date_iso):
    """Real offers for one airport pair and date. Raises FeedError (caller falls back)."""
    if not enabled():
        raise FeedError("no DUFFEL_API_KEY")
    body = {"data": {"slices": [{"origin": origin_iata, "destination": dest_iata, "departure_date": date_iso}],
                     "passengers": [{"type": "adult"}], "cabin_class": "economy", "max_connections": 1}}
    data, meta = post_json(f"{API}?return_offers=true&supplier_timeout=15000", body,
                           headers={"Authorization": f"Bearer {api_key()}", "Duffel-Version": VERSION},
                           ttl=CACHE_S, cache_key=f"duffel:{origin_iata}:{dest_iata}:{date_iso}", timeout=35)
    return parse_offers(data), meta["cache"]
