"""HTTP API for the RFP agent team (rfp_orchestrator, Claude Messages API).

POST /api/runs                     start a run in the background -> {run_id}
GET  /api/runs/{id}/events         server-sent events: full history, then live
GET  /api/runs/{id}                status + agent tree
GET  /api/runs/{id}/files          files the agents wrote (final/ and work/)
GET  /api/runs/{id}/files/{path}   download one of them
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from rfp_orchestrator.api import DATA_DIR, DEFAULT_OUTPUT_ROOT, new_run_id, run_rfp
from rfp_orchestrator.events import Event

load_dotenv()

# Cloudflare drops a response that sends nothing for 100 seconds, and the
# agents can stay quiet longer than that while they work.
PING_SECONDS = 20
# Cost guard: how many runs may execute at the same time on this server.
MAX_PARALLEL_RUNS = int(os.environ.get("RFP_MAX_PARALLEL_RUNS", "2"))
LISTED_AREAS = ("final", "work")

app = FastAPI(title="RFP agent team")


@dataclass
class RunState:
    id: str
    started_at: float = field(default_factory=time.time)
    status: str = "running"  # running | finished | failed
    error: str | None = None
    history: list[str] = field(default_factory=list)  # serialized events, for replay
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    summary: dict | None = None
    task: asyncio.Task | None = None

    async def publish(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str)
        self.history.append(data)
        for q in list(self.subscribers):
            q.put_nowait(data)

    def close(self) -> None:
        for q in list(self.subscribers):
            q.put_nowait(None)


runs: dict[str, RunState] = {}


class RunRequest(BaseModel):
    rfp: str = Field(min_length=50, max_length=400_000)
    instructions: str = Field(default="", max_length=4_000)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "active_runs": _active_runs()}


@app.get("/api/rfp")
async def sample_rfp() -> dict:
    return {"rfp": (DATA_DIR / "rfp-acme-corp.md").read_text(encoding="utf-8")}


@app.post("/api/runs")
async def start_run(req: RunRequest) -> dict:
    if _active_runs() >= MAX_PARALLEL_RUNS:
        raise HTTPException(429, f"{MAX_PARALLEL_RUNS} runs are already in progress. Try again later.")
    state = RunState(id=new_run_id())
    runs[state.id] = state
    state.task = asyncio.create_task(_execute(state, req))
    return {"run_id": state.id}


async def _execute(state: RunState, req: RunRequest) -> None:
    async def sink(event: Event) -> None:
        await state.publish(event.to_dict())

    try:
        result = await run_rfp(
            rfp_text=req.rfp, instructions=req.instructions, run_id=state.id, sinks=[sink]
        )
        state.summary = asdict(result)
        state.status = "finished" if result.ok else "failed"
    except Exception as exc:  # report it to the page rather than dropping the stream
        state.status, state.error = "failed", str(exc)
        await state.publish({"type": "run_error", "run_id": state.id, "data": {"error": str(exc)}})
    finally:
        await state.publish({"type": "stream_end", "run_id": state.id, "data": {"status": state.status}})
        state.close()


@app.get("/api/runs/{run_id}")
async def run_status(run_id: str) -> dict:
    state = _get(run_id)
    return {
        "run_id": state.id,
        "status": state.status,
        "error": state.error,
        "started_at": state.started_at,
        "summary": state.summary,
    }


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    state = _get(run_id)
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    # Snapshot + subscribe in one step (no await in between => no gap, no duplicates).
    backlog = list(state.history)
    done = state.status != "running"
    if not done:
        state.subscribers.add(queue)

    async def body():
        try:
            for data in backlog:
                yield f"data: {data}\n\n"
            if done:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), PING_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {item}\n\n"
        finally:
            state.subscribers.discard(queue)

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/runs/{run_id}/files")
async def run_files(run_id: str) -> list[dict]:
    root = _run_dir(run_id)
    out = []
    for area in LISTED_AREAS:
        for p in sorted((root / area).rglob("*")):
            if p.is_file():
                out.append({"path": str(p.relative_to(root)), "area": area, "size": p.stat().st_size})
    return out


@app.get("/api/runs/{run_id}/files/{path:path}")
async def download(run_id: str, path: str) -> FileResponse:
    root = _run_dir(run_id)
    target = (root / path).resolve()
    if not target.is_relative_to(root) or target.relative_to(root).parts[0] not in LISTED_AREAS:
        raise HTTPException(404, "Not found")
    if not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target, filename=target.name)


# ---- helpers ------------------------------------------------------------- #
def _active_runs() -> int:
    return sum(1 for r in runs.values() if r.status == "running")


def _get(run_id: str) -> RunState:
    state = runs.get(run_id)
    if state is None:
        raise HTTPException(404, "Unknown run")
    return state


def _run_dir(run_id: str) -> Path:
    if not run_id.isalnum():
        raise HTTPException(404, "Unknown run")
    root = (DEFAULT_OUTPUT_ROOT / run_id).resolve()
    if not root.is_dir():
        raise HTTPException(404, "Unknown run")
    return root
