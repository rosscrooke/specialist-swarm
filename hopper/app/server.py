"""Hopper Flask server: /api/plan runs the swarm, /api/rerank re-runs only the Ranker,
/api/crawl plans a Bar Crawl."""
import base64
import hashlib
import os
from datetime import datetime, timedelta
import uuid
from collections import OrderedDict
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory


def load_dotenv(path=Path(__file__).resolve().parent.parent / ".env"):
    """Minimal KEY=VALUE loader so FIVE11_API_KEY can live in hopper/.env (git-ignored).
    Real environment variables always win."""
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()

from . import accounts, bars, flights, geo, guard, rides, tools, weather, world  # noqa: E402 — needs env loaded first
from .agents import PlanError, orchestrate, rerank  # noqa: E402
from .data import MODE_COLORS, PLACES  # noqa: E402
from .live import FeedError  # noqa: E402
from .modes import MODES  # noqa: E402

STATIC = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=str(STATIC))
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024          # no endpoint needs more than a few KB
accounts.init_app(app)
PLANS = OrderedDict()   # plan_id → (feasible trips, explanations, baseline, caps); small LRU


def _inline_script_hash():
    """CSP hash of index.html's one inline <script>, so CSP needs no 'unsafe-inline' for scripts."""
    html = (STATIC / "index.html").read_text()
    script = html.split("<script>")[-1].split("</script>")[0]
    return "sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()


CSP = "; ".join([
    "default-src 'self'",
    f"script-src 'self' https://unpkg.com '{_inline_script_hash()}'",
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com",   # style="" attrs
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: https://tiles.openfreemap.org https://server.arcgisonline.com https://assets.duffel.com",
    "connect-src 'self' https://tiles.openfreemap.org",
    "worker-src 'self' blob:",
    "child-src blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def clean_body():
    """The request's JSON object with internal flags removed — keys starting with "_" are
    set only by the server (e.g. _quick, _visitor), never by the browser."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return {k: v for k, v in body.items() if not str(k).startswith("_")}


@app.before_request
def rate_limit():
    g.visitor = guard.visitor_id(request)
    group = guard.group_for(request.path, request.method)
    if group:
        wait = guard.check(group, g.visitor)
        if wait:
            resp = jsonify({"error": f"You're going a bit fast. Try again in {wait} seconds."})
            resp.status_code = 429
            resp.headers["Retry-After"] = str(wait)
            return resp
    return None


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=(), payment=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "That request is too large."}), 413


@app.get("/api/geocode")
def geocode():
    """Worldwide address / place type-ahead (Photon, cached), biased to the map centre."""
    q = (request.args.get("q") or "").strip()[:120]
    near = None
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
        if -85 <= lat <= 85 and -180 <= lon <= 180:
            near = [lat, lon]
    except (KeyError, ValueError):
        pass
    try:
        return jsonify({"results": geo.search(q, near=near)})
    except FeedError:
        return jsonify({"results": [], "error": "Address search is unavailable right now."}), 503


@app.post("/api/ride-options")
def ride_options():
    """Ride types (simulated fares / ETAs / availability) for one ride leg + Uber/Lyft links."""
    body = clean_body()
    leg = body.get("leg") or {}
    try:
        path = [[float(p[0]), float(p[1])] for p in (leg.get("path") or [])[:1] + (leg.get("path") or [])[-1:]]
        dist, minutes = float(leg["distance_mi"]), float(leg["minutes"])
        surge = min(max(float(leg.get("surge") or 1.0), 1.0), 3.0)
        hour = int(body.get("hour", 12)) % 24
        now_min = body.get("now_min")
        now_min = None if now_min is None else int(now_min) % 1440
    except (KeyError, TypeError, ValueError, IndexError):
        return jsonify({"error": "Send the ride leg with its path, distance, and minutes."}), 400
    if len(path) != 2 or not (0 < dist <= 150) or not (0 < minutes <= 300):
        return jsonify({"error": "That ride leg doesn't look valid."}), 400
    safe = {"path": path, "distance_mi": dist, "minutes": minutes, "surge": surge,
            "frm_name": str(leg.get("frm_name") or "Pickup")[:80], "to_name": str(leg.get("to_name") or "Drop-off")[:80]}
    return jsonify({**rides.for_leg(safe, hour, now_min), "note": rides.simulated_note()})


@app.post("/api/flights")
def flight_options():
    """Door-to-door options with a flight: ground → airport → flight (estimate) → ground."""
    body = clean_body()
    try:
        origin = geo.resolve(body.get("origin_place") or body.get("origin"))
        dest = geo.resolve(body.get("destination_place") or body.get("destination"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    if not origin or not dest:
        return jsonify({"error": "Choose where you're starting and where you're going."}), 422
    for k in (origin, dest):
        geo.ensure_ready(k)
    tz_o = world.timezone_at(*tools.latlon(origin))
    tz_d = world.timezone_at(*tools.latlon(dest))
    today = world.local_now(tz_o).date()
    try:
        date = datetime.strptime(str(body.get("date") or ""), "%Y-%m-%d").date()
    except ValueError:
        date = today + timedelta(days=1)
    if date < today or date > today + timedelta(days=330):
        return jsonify({"error": "Pick a travel date between today and about 11 months out."}), 422
    hour = int(body["hour"]) % 24 if str(body.get("hour", "")).isdigit() else 9
    mode = body.get("mode") if body.get("mode") in ("hustle", "broke", "burn") else "hustle"
    out = flights.plan(origin, dest, date, hour, float(body.get("weight_kg") or 75), orchestrate, tz_o, tz_d, mode)
    if out["error"] and not out["options"]:
        return jsonify({"error": out["error"]}), 422
    return jsonify({**out, "date": date.isoformat(), "hour": hour,
                    "origin_name": tools.name(origin), "destination_name": tools.name(dest),
                    "miles": round(tools.haversine_mi(origin, dest)),
                    "note": out.get("fares_note") or "Flight times and fares are estimates. Check live fares before you book."})


@app.get("/api/reverse")
def reverse():
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify({"error": "lat and lon are required."}), 400
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        return jsonify({"error": "That location isn't valid."}), 422
    try:
        return jsonify(geo.reverse(lat, lon))
    except FeedError:
        return jsonify({"name": "Current location", "address": "", "lat": lat, "lon": lon,
                        "key": geo.make_key(lat, lon)})


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/api/places")
def places():
    return jsonify({"places": [{"key": k, "name": PLACES[k][0], "lat": PLACES[k][1], "lon": PLACES[k][2],
                                "elev_ft": PLACES[k][3]}
                               for k in sorted(geo.landmarks(), key=lambda k: PLACES[k][0])],
                    "colors": MODE_COLORS,
                    "modes": {k: {"label": m["label"], "goal": m["goal"]} for k, m in MODES.items()},
                    "vibes": bars.VIBES})


@app.post("/api/plan")
def plan():
    try:
        result, feasible, why, baseline, caps = orchestrate({**clean_body(), "_visitor": g.visitor})
    except PlanError as e:
        return jsonify({"error": str(e)}), 422
    if result.get("redirect"):
        return jsonify(result)
    plan_id = uuid.uuid4().hex[:10]
    PLANS[plan_id] = (feasible, why, baseline, caps)
    while len(PLANS) > 50:
        PLANS.popitem(last=False)
    return jsonify({**result, "plan_id": plan_id})


@app.post("/api/rerank")
def rerank_plan():
    body = clean_body()
    cached = PLANS.get(body.get("plan_id"))
    if not cached:
        return jsonify({"error": "Plan expired — search again."}), 404
    feasible, why, baseline, caps = cached
    mode = body.get("mode")
    options, trace, notice = rerank(feasible, body.get("weights") or {}, why, baseline,
                                    None if mode == "custom" else mode, caps)
    return jsonify({"options": options, "trace": trace, "notice": notice})


@app.post("/api/crawl")
def crawl():
    body = clean_body()
    if body.get("age_confirmed") is not True:
        return jsonify({"error": "Bar Crawl is 21+. Please confirm your age."}), 403
    try:
        start = geo.resolve(body.get("start_place") or body.get("start"))
        end = geo.resolve(body.get("end_place") or body.get("end")) if (body.get("end_place") or body.get("end")) else None
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    if not start:
        return jsonify({"error": "Pick where the crawl starts."}), 422
    for k in (start, end):
        if k:
            geo.ensure_ready(k)
    stops = max(2, min(int(body.get("stops") or 3), 5))
    vibe = body.get("vibe") if body.get("vibe") in bars.VIBES else "any"
    lat, lon = tools.latlon(start)
    tz = world.timezone_at(lat, lon)
    raw_hour = body.get("hour")
    hour = world.local_now(tz).hour if raw_hour in (None, "", "now") else int(raw_hour) % 24
    per_stop = max(20, min(int(body.get("minutes_per_stop") or 45), 120))
    condition, wx = body.get("weather") or "live", None
    if condition == "live":
        for fetch in ([weather.at] if geo.in_us(lat, lon) else []) + [world.weather_at]:
            try:
                wx = fetch(lat, lon, hour)
                condition = wx["condition"]
                break
            except (FeedError, KeyError, IndexError, TypeError, ValueError):
                continue
        else:
            condition = "clear"
    out, source = bars.plan_crawl(start, end, stops, vibe, hour, per_stop, condition,
                                  bool(body.get("event")), float(body.get("weight_kg") or 75))
    if not out:
        hint = "a busier neighborhood (North Beach, Mission, Castro)" if world.in_sf_area(lat, lon) \
            else "a busier area or a different start"
        if source.startswith("unavailable"):
            return jsonify({"error": "Bar data for this area is unavailable right now. Try again in a minute."}), 503
        return jsonify({"error": f"No {bars.VIBES[vibe].lower()} crawl of {stops} bars within walking "
                                 f"distance of {tools.name(start)}. Try another vibe, fewer stops, or {hint}."}), 422
    units = "mi" if tz.startswith("America/") or tz in ("Europe/London", "Europe/Dublin") else "km"
    return jsonify({**out, "start_name": tools.name(start), "units": units, "tz": tz,
                    "end_name": tools.name(end) if end else None,
                    "weather": wx, "condition": condition, "vibe": vibe, "stops_requested": stops})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5080)), debug=False)
