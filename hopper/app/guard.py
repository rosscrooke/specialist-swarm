"""Abuse protection and cost control.

- Per-visitor rate limits (sliding windows, per minute and per hour) on the expensive and
  sensitive endpoints. Over a limit → HTTP 429 with Retry-After and a friendly message.
- Claude budget: a daily cap for the whole app and a smaller one per visitor. Past either
  cap, plans use the rules + templates fallback (numbers are identical) instead of Claude.
- Visitor identity: the socket address. X-Forwarded-For is trusted only when
  HOPPER_TRUST_PROXY=1 (i.e. when deployed behind a proxy you control) — otherwise anyone
  could spoof it to dodge limits.

In-memory and per-process: right for this prototype; a multi-instance deploy would move the
counters to Redis or similar.
"""
import os
import threading
import time
from collections import defaultdict, deque

# group → [(window seconds, max requests)]
LIMITS = {
    "plan": [(60, 20), (3600, 200)],
    "rerank": [(60, 120)],
    "flights": [(60, 5), (3600, 30)],
    "crawl": [(60, 10), (3600, 60)],
    "auth": [(60, 10), (3600, 60)],
    "rides": [(60, 60)],
    "geocode": [(60, 90), (3600, 1200)],
    "account": [(60, 60)],
}
ROUTES = {
    "/api/plan": "plan", "/api/rerank": "rerank", "/api/flights": "flights", "/api/crawl": "crawl",
    "/api/auth/signup": "auth", "/api/auth/login": "auth", "/api/ride-options": "rides",
    "/api/geocode": "geocode", "/api/reverse": "geocode",
}
CLAUDE_DAILY_CAP = int(os.environ.get("HOPPER_CLAUDE_DAILY_CAP", "400"))           # whole app
CLAUDE_VISITOR_DAILY_CAP = int(os.environ.get("HOPPER_CLAUDE_VISITOR_DAILY_CAP", "40"))

_hits = defaultdict(deque)            # (group, visitor) → request timestamps
_claude = defaultdict(int)            # (day, visitor or "*") → calls
_lock = threading.Lock()


def visitor_id(request):
    if os.environ.get("HOPPER_TRUST_PROXY") == "1":
        fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.remote_addr or "unknown"


def group_for(path, method):
    if path in ROUTES:
        return ROUTES[path]
    if path.startswith("/api/me") and method != "GET":
        return "account"
    return None


def check(group, visitor, now=None):
    """Record a request. Returns 0 if allowed, else seconds until the next one is allowed."""
    now = now or time.time()
    windows = LIMITS[group]
    longest = max(w for w, _ in windows)
    with _lock:
        q = _hits[(group, visitor)]
        while q and now - q[0] > longest:
            q.popleft()
        for window, cap in windows:
            recent = [t for t in q if now - t <= window]
            if len(recent) >= cap:
                return max(1, int(window - (now - recent[0])) + 1)
        q.append(now)
    return 0


def _day():
    return time.strftime("%Y-%m-%d", time.gmtime())


def claude_allowed(visitor, calls=1):
    """Reserve `calls` Claude calls for this visitor today. False → use the fallback."""
    day = _day()
    with _lock:
        if _claude[(day, "*")] + calls > CLAUDE_DAILY_CAP:
            return False
        if _claude[(day, visitor)] + calls > CLAUDE_VISITOR_DAILY_CAP:
            return False
        _claude[(day, "*")] += calls
        _claude[(day, visitor)] += calls
        for key in [k for k in _claude if k[0] != day]:      # drop yesterday's counters
            del _claude[key]
    return True


def claude_usage(visitor):
    day = _day()
    with _lock:
        return {"today": _claude[(day, "*")], "cap": CLAUDE_DAILY_CAP,
                "visitor_today": _claude[(day, visitor)], "visitor_cap": CLAUDE_VISITOR_DAILY_CAP}


def reset():
    """Clear all counters (tests)."""
    with _lock:
        _hits.clear()
        _claude.clear()
