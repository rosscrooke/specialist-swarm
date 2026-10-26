"""Abuse protection and cost control — offline."""
import base64
import hashlib

from app import agents, guard
from app.server import STATIC, app


def test_rate_limit_returns_429_with_retry_after():
    c = app.test_client()
    body = {"leg": {"path": [[37.79, -122.39], [37.80, -122.40]], "distance_mi": 1.2, "minutes": 6}}
    codes = [c.post("/api/ride-options", json=body).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    r = c.post("/api/ride-options", json=body)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1 and "Try again" in r.json["error"]


def test_limits_are_per_visitor():
    for _ in range(5):
        assert guard.check("flights", "1.1.1.1") == 0
    assert guard.check("flights", "1.1.1.1") > 0           # 6th flight search in a minute
    assert guard.check("flights", "2.2.2.2") == 0           # someone else is unaffected


def test_sliding_window_frees_up_after_the_window():
    t0 = 1_000_000.0
    for i in range(5):
        assert guard.check("flights", "v", now=t0 + i) == 0
    assert guard.check("flights", "v", now=t0 + 10) > 0
    assert guard.check("flights", "v", now=t0 + 61) == 0    # first request aged out


def test_auth_endpoints_are_rate_limited_per_ip():
    c = app.test_client()
    creds = {"email": "nobody@example.test", "password": "wrong-password"}
    codes = [c.post("/api/auth/login", json={**creds, "email": f"u{i}@example.test"}).status_code for i in range(11)]
    assert codes[-1] == 429 and 429 not in codes[:10]       # different emails, same IP


def test_forwarded_for_is_ignored_unless_proxy_is_trusted(monkeypatch):
    with app.test_request_context(headers={"X-Forwarded-For": "9.9.9.9"}, environ_base={"REMOTE_ADDR": "10.0.0.1"}):
        from flask import request
        monkeypatch.delenv("HOPPER_TRUST_PROXY", raising=False)
        assert guard.visitor_id(request) == "10.0.0.1"
        monkeypatch.setenv("HOPPER_TRUST_PROXY", "1")
        assert guard.visitor_id(request) == "9.9.9.9"


def test_claude_caps_per_visitor_and_global(monkeypatch):
    monkeypatch.setattr(guard, "CLAUDE_VISITOR_DAILY_CAP", 4)
    monkeypatch.setattr(guard, "CLAUDE_DAILY_CAP", 6)
    assert guard.claude_allowed("a", 2) and guard.claude_allowed("a", 2)
    assert not guard.claude_allowed("a", 2)                 # visitor a used 4/4
    assert guard.claude_allowed("b", 2)                     # global 6/6 now
    assert not guard.claude_allowed("c", 2)                 # global cap reached
    assert guard.claude_usage("a") == {"today": 6, "cap": 6, "visitor_today": 4, "visitor_cap": 4}


def test_planner_falls_back_to_rules_when_claude_budget_is_spent(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(agents, "_llm", lambda: sentinel)
    monkeypatch.setattr(guard, "claude_allowed", lambda visitor, calls=1: False)
    result, *_ = agents.orchestrate({"origin": "ferry_building", "destination": "coit_tower", "weather": "clear",
                                     "_visitor": "v"})
    assert result["stats"]["llm"] is False
    assert any(t["agent"] == "Cost guard" for t in result["trace"])


def test_browser_cannot_set_internal_flags():
    c = app.test_client()
    # _quick would make the planner raise instead of offering flights; it must be ignored.
    r = c.post("/api/plan", json={"origin": "ferry_building", "weather": "clear", "_quick": True,
                                  "destination_place": {"name": "Times Square", "lat": 40.758, "lon": -73.9855}})
    assert r.status_code == 200 and r.json["redirect"] == "flights"


def test_security_headers_and_csp_hash_matches_inline_script():
    r = app.test_client().get("/")
    h = r.headers
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin" and "camera=()" in h["Permissions-Policy"]
    csp = h["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    script = (STATIC / "index.html").read_text().split("<script>")[-1].split("</script>")[0]
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp


def test_api_responses_are_not_cached():
    assert app.test_client().get("/api/places").headers["Cache-Control"] == "no-store"


def test_oversized_requests_are_rejected():
    r = app.test_client().post("/api/plan", data="x" * (70 * 1024), content_type="application/json")
    assert r.status_code == 413 and "too large" in r.json["error"]
