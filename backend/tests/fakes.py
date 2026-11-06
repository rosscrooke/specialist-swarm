"""Scripted fake Anthropic client shared by the offline tests."""

from __future__ import annotations

import asyncio
import itertools
from types import SimpleNamespace

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
