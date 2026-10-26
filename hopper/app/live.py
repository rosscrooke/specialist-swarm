"""Tiny HTTP layer for live feeds: TTL cache, optional disk cache, and a rolling
per-hour call budget (511's free tier allows ~60 requests/hour per key).

Every feed module goes through `get_json` so caching and budgets live in one place,
and `HOPPER_OFFLINE=1` turns every live feed off for tests and demos.
"""
import gzip
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

USER_AGENT = "Hopper-POC/0.2 (prototype; contact: local)"
DISK_CACHE = Path(__file__).resolve().parent.parent / ".cache"

_mem = {}
_lock = threading.Lock()


class FeedError(RuntimeError):
    pass


class Budget:
    """Rolling one-hour call budget. `take()` returns False once the budget is spent."""

    def __init__(self, per_hour):
        self.per_hour = per_hour
        self.calls = deque()
        self.lock = threading.Lock()

    def take(self):
        now = time.time()
        with self.lock:
            while self.calls and now - self.calls[0] > 3600:
                self.calls.popleft()
            if len(self.calls) >= self.per_hour:
                return False
            self.calls.append(now)
            return True

    @property
    def used(self):
        now = time.time()
        return sum(1 for t in self.calls if now - t <= 3600)


def offline():
    return os.environ.get("HOPPER_OFFLINE") == "1"


def post_json(url, payload, headers=None, ttl=0, cache_key=None, timeout=30):
    """POST JSON → (data, meta). Optional in-memory cache by `cache_key` (never includes
    secrets). HTTP errors raise FeedError with the API's own error title when it has one."""
    if offline():
        raise FeedError("offline mode")
    now = time.time()
    if cache_key and ttl:
        with _lock:
            hit = _mem.get(("POST", cache_key))
        if hit and now - hit[0] < ttl:
            return hit[1], {"cache": "memory"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                          "Content-Type": "application/json", "Accept-Encoding": "gzip",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        try:
            errs = json.loads(raw.decode("utf-8-sig")).get("errors") or []
            detail = errs[0].get("title") or errs[0].get("message") if errs else ""
        except (ValueError, AttributeError):
            detail = ""
        raise FeedError(f"HTTP {e.code}{': ' + detail if detail else ''}"[:160]) from None
    except Exception as e:  # noqa: BLE001 — network failures degrade to a fallback
        raise FeedError(f"{type(e).__name__}: {e}"[:160]) from None
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    data = json.loads(body.decode("utf-8-sig"))
    if cache_key and ttl:
        with _lock:
            _mem[("POST", cache_key)] = (now, data)
    return data, {"cache": "live"}


def get_json(url, params=None, ttl=60, disk_ttl=None, budget=None, timeout=12, redact=(),
             cache_only=False):
    """GET a JSON document with caching. Returns (data, meta) where meta says cache/live.

    `redact` lists query params (e.g. api_key) kept out of cache keys and error messages.
    `cache_only=True` never touches the network: it raises FeedError on a cache miss.
    """
    if offline():
        raise FeedError("offline mode")
    params = params or {}
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    key = url + "?" + urllib.parse.urlencode(sorted((k, v) for k, v in params.items()
                                                    if k not in redact))
    now = time.time()
    with _lock:
        hit = _mem.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], {"cache": "memory"}
    disk_file = DISK_CACHE / (hashlib.sha1(key.encode()).hexdigest() + ".json") if disk_ttl else None
    if disk_file and disk_file.exists() and now - disk_file.stat().st_mtime < disk_ttl:
        data = json.loads(disk_file.read_text())
        with _lock:
            _mem[key] = (now, data)
        return data, {"cache": "disk"}
    if cache_only:
        raise FeedError("not cached yet")
    if budget is not None and not budget.take():
        raise FeedError("hourly call budget spent")
    # 511 only serves gzip and answers 406 to urllib's default "Accept-Encoding: identity".
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT,
                                                "Accept": "application/json",
                                                "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            if body[:2] == b"\x1f\x8b":
                body = gzip.decompress(body)
            # 511 prefixes its JSON with a UTF-8 BOM; utf-8-sig strips it.
            data = json.loads(body.decode("utf-8-sig"))
    except Exception as e:  # noqa: BLE001 — every feed failure degrades to a fallback
        raise FeedError(f"{type(e).__name__}: {getattr(e, 'code', '') or e}"[:160]) from None
    with _lock:
        _mem[key] = (now, data)
    if disk_file:
        DISK_CACHE.mkdir(exist_ok=True)
        disk_file.write_text(json.dumps(data))
    return data, {"cache": "live"}
