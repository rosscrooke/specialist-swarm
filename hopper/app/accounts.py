"""Accounts, saved places, and trip history (SQLite, prototype-grade but done properly).

- Passwords: werkzeug's salted scrypt hashes; never stored or logged in plain text.
- Sessions: Flask's signed cookie (HttpOnly, SameSite=Lax). The signing key comes from
  HOPPER_SECRET_KEY, or is generated once into data/.secret_key (git-ignored).
- Every state-changing endpoint requires a JSON body, so a plain cross-site form post
  can't trigger it (JSON needs a CORS preflight this app never grants).
- Login attempts are rate-limited per email; error messages don't reveal which emails exist.
"""
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

from flask import Blueprint, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

DATA_DIR = Path(os.environ.get("HOPPER_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
MAX_FAILS, FAIL_WINDOW_S = 5, 900

bp = Blueprint("accounts", __name__)
_fails = defaultdict(deque)
_fails_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  pw_hash TEXT NOT NULL, prefs TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS places (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label TEXT NOT NULL, name TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trips (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL, mode TEXT,
  summary TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS trips_user ON trips(user_id, created DESC);
"""


def secret_key():
    if os.environ.get("HOPPER_SECRET_KEY"):
        return os.environ["HOPPER_SECRET_KEY"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / ".secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return f.read_text().strip()


def init_app(app):
    app.config.update(SECRET_KEY=secret_key(), SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)
    with _connect() as db:
        db.executescript(SCHEMA)
    app.register_blueprint(bp)
    app.teardown_appcontext(_close)


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR / "hopper.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def _close(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def err(message, status=400):
    return jsonify({"error": message}), status


def json_body():
    if not request.is_json:
        return None
    return request.get_json(silent=True) or {}


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return db().execute("SELECT id, email, name, prefs FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return err("Sign in to use this.", 401)
        g.user = user
        return fn(*a, **kw)
    return wrapper


def _rate_limited(email):
    with _fails_lock:
        q = _fails[email]
        while q and time.time() - q[0] > FAIL_WINDOW_S:
            q.popleft()
        return len(q) >= MAX_FAILS


def _record_fail(email):
    with _fails_lock:
        _fails[email].append(time.time())


def _user_json(u):
    return {"id": u["id"], "email": u["email"], "name": u["name"], "prefs": json.loads(u["prefs"] or "{}")}


def _place_point(p, field):
    """Validate a {name, lat, lon} point from the client."""
    if not isinstance(p, dict):
        raise ValueError(f"{field} is missing.")
    try:
        lat, lon = float(p["lat"]), float(p["lon"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{field} needs a latitude and longitude.") from None
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        raise ValueError(f"{field} has an invalid location.")
    return {"name": str(p.get("name") or "Pinned location")[:80], "lat": round(lat, 6), "lon": round(lon, 6),
            "key": str(p.get("key") or "")[:40]}


# ── Auth ─────────────────────────────────────────────────────────────────────

@bp.post("/api/auth/signup")
def signup():
    body = json_body()
    if body is None:
        return err("Send JSON.", 415)
    email = str(body.get("email", "")).strip().lower()
    name = str(body.get("name", "")).strip()[:60]
    password = str(body.get("password", ""))
    if not EMAIL.match(email):
        return err("Enter a valid email address.")
    if not name:
        return err("Enter your name.")
    if len(password) < 8:
        return err("Use a password with at least 8 characters.")
    try:
        cur = db().execute("INSERT INTO users (email, name, pw_hash, created) VALUES (?, ?, ?, ?)",
                           (email, name, generate_password_hash(password), now()))
        db().commit()
    except sqlite3.IntegrityError:
        return err("An account with that email already exists. Sign in instead.", 409)
    session.clear()
    session.permanent = True
    session["uid"] = cur.lastrowid
    return me()


@bp.post("/api/auth/login")
def login():
    body = json_body()
    if body is None:
        return err("Send JSON.", 415)
    email = str(body.get("email", "")).strip().lower()
    if _rate_limited(email):
        return err("Too many attempts. Try again in 15 minutes.", 429)
    row = db().execute("SELECT id, pw_hash FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not check_password_hash(row["pw_hash"], str(body.get("password", ""))):
        _record_fail(email)
        return err("Email or password is incorrect.", 401)
    session.clear()
    session.permanent = True
    session["uid"] = row["id"]
    return me()


@bp.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"user": None})


# ── Profile, places, trips ───────────────────────────────────────────────────

@bp.get("/api/me")
def me():
    user = current_user()
    if not user:
        return jsonify({"user": None, "places": [], "trips": []})
    places = db().execute("SELECT id, label, name, lat, lon FROM places WHERE user_id = ? ORDER BY "
                          "CASE label WHEN 'Home' THEN 0 WHEN 'Work' THEN 1 ELSE 2 END, created",
                          (user["id"],)).fetchall()
    trips = db().execute("SELECT id, created, origin, destination, mode, summary FROM trips "
                         "WHERE user_id = ? ORDER BY created DESC, id DESC LIMIT 30", (user["id"],)).fetchall()
    return jsonify({"user": _user_json(user),
                    "places": [dict(p) for p in places],
                    "trips": [{"id": t["id"], "created": t["created"], "mode": t["mode"],
                               "origin": json.loads(t["origin"]), "destination": json.loads(t["destination"]),
                               "summary": json.loads(t["summary"])} for t in trips]})


@bp.put("/api/me/prefs")
@login_required
def save_prefs():
    body = json_body()
    if body is None:
        return err("Send JSON.", 415)
    prefs = json.loads(g.user["prefs"] or "{}")
    if "weight_kg" in body:
        prefs["weight_kg"] = max(30, min(float(body["weight_kg"]), 250))
    if "default_mode" in body and body["default_mode"] in ("hustle", "broke", "burn", "barcrawl"):
        prefs["default_mode"] = body["default_mode"]
    db().execute("UPDATE users SET prefs = ? WHERE id = ?", (json.dumps(prefs), g.user["id"]))
    db().commit()
    return me()


@bp.post("/api/me/places")
@login_required
def save_place():
    body = json_body()
    if body is None:
        return err("Send JSON.", 415)
    label = str(body.get("label", "")).strip()[:30] or "Saved"
    try:
        p = _place_point(body, "Place")
    except ValueError as e:
        return err(str(e))
    uid = g.user["id"]
    if label in ("Home", "Work"):             # one Home, one Work — saving again replaces it
        db().execute("DELETE FROM places WHERE user_id = ? AND label = ?", (uid, label))
    elif db().execute("SELECT COUNT(*) FROM places WHERE user_id = ?", (uid,)).fetchone()[0] >= 25:
        return err("You can save up to 25 places. Remove one first.")
    db().execute("INSERT INTO places (user_id, label, name, lat, lon, created) VALUES (?, ?, ?, ?, ?, ?)",
                 (uid, label, p["name"], p["lat"], p["lon"], now()))
    db().commit()
    return me()


@bp.delete("/api/me/places/<int:place_id>")
@login_required
def delete_place(place_id):
    db().execute("DELETE FROM places WHERE id = ? AND user_id = ?", (place_id, g.user["id"]))
    db().commit()
    return me()


@bp.post("/api/me/trips")
@login_required
def save_trip():
    body = json_body()
    if body is None:
        return err("Send JSON.", 415)
    try:
        origin = _place_point(body.get("origin"), "Start")
        destination = _place_point(body.get("destination"), "Destination")
    except ValueError as e:
        return err(str(e))
    s = body.get("summary") or {}
    summary = {"label": str(s.get("label", ""))[:80], "minutes": round(float(s.get("minutes", 0)), 1),
               "cost": round(float(s.get("cost", 0)), 2), "kcal": int(s.get("kcal", 0)),
               "modes": [str(m)[:12] for m in (s.get("modes") or [])][:6],
               "kind": "crawl" if s.get("kind") == "crawl" else "trip"}
    mode = str(body.get("mode", ""))[:12]
    db().execute("INSERT INTO trips (user_id, created, origin, destination, mode, summary) VALUES (?, ?, ?, ?, ?, ?)",
                 (g.user["id"], now(), json.dumps(origin), json.dumps(destination), mode, json.dumps(summary)))
    db().commit()
    return me()


@bp.delete("/api/me/trips")
@login_required
def clear_trips():
    db().execute("DELETE FROM trips WHERE user_id = ?", (g.user["id"],))
    db().commit()
    return me()
