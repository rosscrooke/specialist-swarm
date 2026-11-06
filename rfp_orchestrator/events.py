"""Event stream of a run.

Every interesting thing (agent spawned, tool call, delegation rejected, agent
finished, ...) is emitted as an `Event`. Sinks are plain async callables, so
the frontend can plug in an SSE/WebSocket sink without touching the runtime.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

EventType = Literal[
    "run_started",
    "run_finished",
    "agent_started",
    "agent_text",
    "agent_tool_call",
    "delegation_rejected",
    "agent_finished",
    "agent_error",
    "file_written",
]


@dataclass
class Event:
    type: EventType
    run_id: str
    agent_id: str | None = None
    agent_name: str | None = None
    parent_id: str | None = None
    depth: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


EventSink = Callable[[Event], Awaitable[None]]


class EventBus:
    def __init__(self, sinks: list[EventSink] | None = None) -> None:
        self._sinks: list[EventSink] = list(sinks or [])

    def add_sink(self, sink: EventSink) -> None:
        self._sinks.append(sink)

    async def emit(self, event: Event) -> None:
        for sink in self._sinks:
            try:
                await sink(event)
            except Exception as exc:  # a broken sink must never kill the run
                print(f"[event sink error] {exc!r}")


class JsonlSink:
    """Appends every event as one JSON line (replayable by the frontend)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    async def __call__(self, event: Event) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.to_json() + "\n")


class ConsoleSink:
    """Readable tree view for the terminal demo."""

    def __init__(self, show_text: bool = False) -> None:
        self.show_text = show_text

    async def __call__(self, e: Event) -> None:
        indent = "  " * ((e.depth or 0) + 1)
        who = f"{e.agent_name}#{e.agent_id}" if e.agent_id else ""
        d = e.data
        if e.type == "run_started":
            print(f"=== run {e.run_id} started ===", flush=True)
        elif e.type == "agent_started":
            print(f"{indent}▶ {who} ({d.get('model')}) task: {_short(d.get('task', ''))}", flush=True)
        elif e.type == "agent_tool_call":
            print(f"{indent}  · {who} → {d.get('tool')} {_short(json.dumps(d.get('input', {}), ensure_ascii=False), 100)}", flush=True)
        elif e.type == "delegation_rejected":
            print(f"{indent}  ✗ {who} delegation rejected: {d.get('reason')}", flush=True)
        elif e.type == "agent_text" and self.show_text:
            print(f"{indent}  “{_short(d.get('text', ''), 200)}”", flush=True)
        elif e.type == "agent_finished":
            u = d.get("usage", {})
            print(
                f"{indent}✔ {who} done in {d.get('duration_s', 0):.1f}s "
                f"(turns={d.get('turns')}, in={u.get('input_tokens')}, out={u.get('output_tokens')})",
                flush=True,
            )
        elif e.type == "agent_error":
            print(f"{indent}! {who} error: {d.get('error')}", flush=True)
        elif e.type == "file_written":
            print(f"{indent}  💾 {d.get('path')}", flush=True)
        elif e.type == "run_finished":
            print(f"=== run {e.run_id} finished: {d.get('summary')} ===", flush=True)


def _short(text: str, n: int = 80) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"
