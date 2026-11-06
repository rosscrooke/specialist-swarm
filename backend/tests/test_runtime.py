"""Offline tests for the orchestration runtime (no API calls).

A scripted fake client plays every agent so we can check that the hierarchy
limits are enforced in code.

    .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from rfp_orchestrator.api import run_rfp
from rfp_orchestrator.config import Limits

from .fakes import FakeClient

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "synthetic-data"
def test_hierarchy_limits(tmp_path):
    client = FakeClient()
    events = []

    async def sink(e):
        events.append(e)

    result = asyncio.run(
        run_rfp(
            DATA / "rfp-acme-corp.md",
            extra_inputs=[DATA / "product-overview.md"],
            output_root=tmp_path,
            limits=Limits(),
            sinks=[sink],
            client=client,
        )
    )

    assert result.ok
    by_depth = {}
    for a in result.agents:
        by_depth.setdefault(a["depth"], []).append(a)
    assert len(by_depth[0]) == 1
    assert len(by_depth[1]) == 5  # orchestrator: unlimited
    for spec in by_depth[1]:
        assert len(spec["children"]) == 3  # 5 requested, capped at 3
    assert len(by_depth[2]) == 15
    assert 3 not in by_depth

    # helpers never got a delegate tool
    for call in client.calls:
        names = {t["name"] for t in call["tools"]}
        if "Document Analyst" in call["system"]:
            assert "delegate" not in names

    rejected = [e for e in events if e.type == "delegation_rejected"]
    assert len(rejected) == 5 * 3  # 2 over the cap + 1 roster violation per specialist
    assert any("not in your roster" in e.data["reason"] for e in rejected)

    # path traversal blocked, deliverables written
    assert (tmp_path / result.run_id / "final" / "proposal-response.docx").exists()
    assert (tmp_path / result.run_id / "events.jsonl").read_text().count("\n") == len(events)


def test_total_agent_cap(tmp_path):
    result = asyncio.run(
        run_rfp(
            DATA / "rfp-acme-corp.md",
            output_root=tmp_path,
            limits=Limits(max_total_agents=4),
            client=FakeClient(),
        )
    )
    assert len(result.agents) == 4
