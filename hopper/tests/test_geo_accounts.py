"""Place search (offline, sample payloads) and accounts (temp SQLite)."""
import pytest

from app import accounts, geo, tools
from app.data import PLACES
from app.server import app

PHOTON = {"features": [
    {"geometry": {"coordinates": [-122.395091, 37.7872405]},
     "properties": {"name": "500 Folsom", "housenumber": "500", "street": "Folsom Street",
                    "district": "Rincon Hill", "osm_value": "yes"}},
    {"geometry": {"coordinates": [-122.395091, 37.7872405]},          # duplicate
     "properties": {"name": "500 Folsom", "housenumber": "510", "street": "Folsom Street"}},
    {"geometry": {"coordinates": [-122.2711, 37.8044]},               # Oakland — fine now (worldwide)
     "properties": {"name": "Oakland City Hall", "city": "Oakland", "state": "California", "countrycode": "US"}},
    {"geometry": {"coordinates": [-122.3790, 37.6213]},               # SFO — allowed
     "properties": {"name": "SFO International Terminal"}},
]}


def test_parse_photon_dedupes_and_labels_worldwide_results():
    out = geo.parse_photon(PHOTON)
    assert [r["name"] for r in out] == ["500 Folsom", "Oakland City Hall", "SFO International Terminal"]
    assert out[0]["address"] == "500 Folsom Street, Rincon Hill"
    assert out[1]["address"] == "Oakland, California"


def test_register_makes_geo_places_usable_by_tools():
    key = geo.register("Tartine Bakery", 37.76137, -122.42410, elev=60)
    assert key == "geo:37.76137,-122.42410"
    assert tools.name(key) == "Tartine Bakery" and tools.in_sf(key)
    assert tools.walk_leg(key, "dolores_park").distance_mi > 0
    assert key not in geo.landmarks()


def test_register_accepts_any_city_but_rejects_invalid_coordinates():
    assert geo.register("Louvre", 48.8606, 2.3376).startswith("geo:48.86")
    with pytest.raises(ValueError):
        geo.register("Nowhere", 123.0, 2.0)


def test_resolve_accepts_landmarks_geo_keys_and_points():
    assert geo.resolve("ferry_building") == "ferry_building"
    assert geo.resolve("geo:37.78724,-122.39509").startswith("geo:")
    assert geo.resolve({"name": "X", "lat": 37.79, "lon": -122.40}) == "geo:37.79000,-122.40000"
    assert geo.resolve("nowhere") is None


def test_dynamic_places_are_capped(monkeypatch):
    monkeypatch.setattr(geo, "MAX_DYNAMIC", 3)
    keys = [geo.register(f"p{i}", 37.75 + i / 1000, -122.45) for i in range(5)]
    assert keys[0] not in PLACES and keys[-1] in PLACES


def test_address_text_is_not_fuzzy_matched_to_a_landmark():
    from app.agents import match_place
    assert match_place("500 folsom st") is None
    assert match_place("coit tower") == "coit_tower"


# ── Accounts ────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "DATA_DIR", tmp_path)
    with accounts._connect() as db:
        db.executescript(accounts.SCHEMA)
    accounts._fails.clear()
    return app.test_client()


CREDS = {"email": "rider@example.test", "name": "Test Rider", "password": "correct-horse-1"}


def test_signup_login_logout_flow(client):
    r = client.post("/api/auth/signup", json=CREDS)
    assert r.status_code == 200 and r.json["user"]["name"] == "Test Rider"
    assert client.get("/api/me").json["user"]["email"] == CREDS["email"]
    client.post("/api/auth/logout", json={})
    assert client.get("/api/me").json["user"] is None
    r = client.post("/api/auth/login", json={"email": CREDS["email"], "password": CREDS["password"]})
    assert r.status_code == 200 and r.json["user"]["email"] == CREDS["email"]


def test_password_is_hashed_never_stored_plain(client):
    client.post("/api/auth/signup", json=CREDS)
    with accounts._connect() as db:
        stored = db.execute("SELECT pw_hash FROM users").fetchone()[0]
    assert CREDS["password"] not in stored and stored.startswith(("scrypt:", "pbkdf2:"))


def test_signup_validation_and_duplicates(client):
    assert client.post("/api/auth/signup", json={**CREDS, "email": "bad"}).status_code == 400
    assert client.post("/api/auth/signup", json={**CREDS, "password": "short"}).status_code == 400
    client.post("/api/auth/signup", json=CREDS)
    assert client.post("/api/auth/signup", json=CREDS).status_code == 409


def test_login_errors_are_generic_and_rate_limited(client):
    client.post("/api/auth/signup", json=CREDS)
    client.post("/api/auth/logout", json={})
    wrong = {"email": CREDS["email"], "password": "nope-nope"}
    r = client.post("/api/auth/login", json=wrong)
    assert r.status_code == 401 and "incorrect" in r.json["error"]
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.test", "password": "x" * 9})
    assert unknown.json["error"] == r.json["error"]                     # no account enumeration
    for _ in range(5):
        client.post("/api/auth/login", json=wrong)
    assert client.post("/api/auth/login", json={**wrong, "password": CREDS["password"]}).status_code == 429


def test_state_changes_require_json(client):
    r = client.post("/api/auth/signup", data=CREDS)                     # form post, not JSON
    assert r.status_code == 415


def test_saved_places_home_replaces_and_require_sign_in(client):
    point = {"label": "Home", "name": "500 Folsom", "lat": 37.78724, "lon": -122.39509}
    assert client.post("/api/me/places", json=point).status_code == 401
    client.post("/api/auth/signup", json=CREDS)
    client.post("/api/me/places", json=point)
    r = client.post("/api/me/places", json={**point, "name": "New home", "lat": 37.76})
    homes = [p for p in r.json["places"] if p["label"] == "Home"]
    assert len(homes) == 1 and homes[0]["name"] == "New home"
    assert client.post("/api/me/places", json={**point, "label": "Paris", "lat": 48.86, "lon": 2.34}).status_code == 200
    assert client.post("/api/me/places", json={**point, "lat": 123.0}).status_code == 400
    pid = homes[0]["id"]
    assert [p["label"] for p in client.delete(f"/api/me/places/{pid}").json["places"]] == ["Paris"]


def test_trip_history_records_newest_first(client):
    client.post("/api/auth/signup", json=CREDS)
    base = {"origin": {"name": "Ferry Building", "lat": 37.7955, "lon": -122.3937},
            "destination": {"name": "Coit Tower", "lat": 37.8024, "lon": -122.4058}, "mode": "burn"}
    client.post("/api/me/trips", json={**base, "summary": {"label": "first", "minutes": 20, "cost": 0, "kcal": 90}})
    r = client.post("/api/me/trips", json={**base, "summary": {"label": "second", "minutes": 12, "cost": 11.95}})
    assert [t["summary"]["label"] for t in r.json["trips"]] == ["second", "first"]
    assert client.delete("/api/me/trips").json["trips"] == []


def test_users_cannot_see_each_others_data(client):
    client.post("/api/auth/signup", json=CREDS)
    client.post("/api/me/places", json={"label": "Work", "name": "Office", "lat": 37.79, "lon": -122.40})
    client.post("/api/auth/logout", json={})
    client.post("/api/auth/signup", json={**CREDS, "email": "other@example.test"})
    assert client.get("/api/me").json["places"] == []
