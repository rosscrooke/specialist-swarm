"""Offline API tests: the FastAPI app driven end to end with the fake client."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from rfp_orchestrator.api import run_rfp

from .fakes import FakeClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    async def fake_run_rfp(**kwargs):
        return await run_rfp(client=FakeClient(), output_root=tmp_path, **kwargs)

    monkeypatch.setattr(main, "run_rfp", fake_run_rfp)
    monkeypatch.setattr(main, "DEFAULT_OUTPUT_ROOT", tmp_path)
    main.runs.clear()
    with TestClient(main.app) as c:
        yield c


def _wait_done(c, run_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = c.get(f"/api/runs/{run_id}").json()["status"]
        if status != "running":
            return status
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_run_lifecycle(client):
    rfp = client.get("/api/rfp").json()["rfp"]
    run_id = client.post("/api/runs", json={"rfp": rfp}).json()["run_id"]
    assert _wait_done(client, run_id) == "finished"

    # Events endpoint replays the full history and then closes.
    with client.stream("GET", f"/api/runs/{run_id}/events") as r:
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types[0] == "run_started" and types[-1] == "stream_end"
    assert types.count("agent_started") == 1 + 5 + 15
    assert "delegation_rejected" in types

    files = client.get(f"/api/runs/{run_id}/files").json()
    paths = {f["path"] for f in files}
    assert "final/proposal-response.docx" in paths
    assert not any(p.startswith("inputs/") for p in paths)

    r = client.get(f"/api/runs/{run_id}/files/final/proposal-response.md")
    assert r.status_code == 200 and "Proposal" in r.text
    assert client.get(f"/api/runs/{run_id}/files/inputs/rfp.md").status_code == 404
    assert client.get(f"/api/runs/{run_id}/files/../../etc/passwd").status_code == 404
    assert client.get("/api/runs/nope/events").status_code == 404


def test_rejects_too_short_rfp(client):
    assert client.post("/api/runs", json={"rfp": "hi"}).status_code == 422
