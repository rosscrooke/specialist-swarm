"""Offline tests for the orchestration runtime (no API calls).

A scripted fake client plays every agent so we can check that the hierarchy
limits are enforced in code.

    .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path
from types import SimpleNamespace

from rfp_orchestrator.api import run_rfp
from rfp_orchestrator.config import Limits

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "synthetic-data"
_ids = itertools.count()


def tool(name, **inp):
    return SimpleNamespace(type="tool_use", id=f"tu_{next(_ids)}", name=name, input=inp)


def text(t):
    return SimpleNamespace(type="text", text=t)


def msg(content, stop="tool_use", model="fake"):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage, model=model)


class FakeClient:
    """Mimics client.beta.messages.stream(...) with a scripted policy."""

    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        reply = self._policy(kwargs)

        class _Ctx:
            async def __aenter__(self_inner):
                return SimpleNamespace(get_final_message=self._final(reply))

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()

    @staticmethod
    def _final(reply):
        async def f():
            await asyncio.sleep(0.01)
            return reply

        return f

    def _policy(self, kw):
        system = kw["system"]
        turn = sum(1 for m in kw["messages"] if m["role"] == "assistant")
        tool_names = {t["name"] for t in kw["tools"]}
        role = system.split(".")[0]

        if role.startswith("\nYou are the Bid Lead") or "Bid Lead" in role:
            if turn == 0:
                return msg(
                    [tool("delegate", agent=a, task=f"Analyse the RFP for lane {a}, read inputs/.")
                     for a in ("requirements_analyst", "technical_fit", "pricing", "legal", "competitive")]
                )
            if turn == 1:
                return msg([tool("write_final_proposal", title="Proposal", markdown="# Exec summary\n" + "- x\n" * 30)])
            return msg([text("Done. Deliverable written.")], stop="end_turn")

        if "delegate" in tool_names:  # a specialist
            if turn == 0:
                calls = [tool("delegate", agent="document_analyst", task=f"Extract facts number {i} from inputs/")
                         for i in range(5)]
                calls.append(tool("delegate", agent="pricing", task="Trying to call a peer specialist here."))
                return msg(calls)
            return msg([text("Specialist report.")], stop="end_turn")

        # helper
        if turn == 0:
            return msg([tool("read_file", path="inputs/rfp-acme-corp.md"), tool("read_file", path="../../etc/passwd")])
        return msg([text("Helper findings.")], stop="end_turn")


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
