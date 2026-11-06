"""HTTP API for the Deal Desk swarm.

POST /api/runs starts a session, GET /api/runs/{id}/events streams its events
as server-sent events, and the files routes hand out what the agents wrote.
"""

import asyncio
import json
from pathlib import Path

from anthropic import AsyncAnthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "synthetic-data"
SWARM = json.loads((ROOT / "swarm.json").read_text()) if (ROOT / "swarm.json").exists() else {}
BETAS = ["managed-agents-2026-04-01"]
# Cloudflare drops a response that sends nothing for 100 seconds, and the
# swarm can stay quiet longer than that while the specialists work.
PING_SECONDS = 20

client = AsyncAnthropic()
app = FastAPI()

# Kickoff messages waiting for their event stream to open. The stream only
# carries events that happen after it opens, so the message goes out from
# inside the stream handler.
pending: dict[str, str] = {}


class RunRequest(BaseModel):
    rfp: str


def kickoff(rfp: str) -> str:
    docs = [f"=====  DOCUMENT: rfp.md  =====\n{rfp}"] + [
        f"=====  DOCUMENT: {p.name}  =====\n{p.read_text()}"
        for p in (DATA / "past-wins.json", DATA / "product-overview.md")
    ]
    return (
        "An RFP has just landed. Please run the standard Deal Desk process:\n"
        "1. Read the RFP yourself.\n"
        "2. Delegate to all four specialists in parallel.\n"
        "3. Synthesise their replies.\n"
        "4. Produce the final proposal response as a branded Word document "
        "if you have access to a docx skill; otherwise output the response "
        "as a structured markdown document.\n\n"
        "Specialists have their own skills attached for their respective "
        "domains. Move fast — the RFP deadline is real.\n\n" + "\n\n".join(docs)
    )


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "swarm": bool(SWARM)}


@app.get("/api/rfp")
async def sample_rfp() -> dict:
    return {"rfp": (DATA / "rfp-acme-corp.md").read_text()}


@app.post("/api/runs")
async def start_run(req: RunRequest) -> dict:
    if not SWARM:
        raise HTTPException(503, "No swarm.json. Run `uv run python -m app.setup` first.")
    session = await client.beta.sessions.create(
        agent=SWARM["coordinator_id"],
        environment_id=SWARM["environment_id"],
        title="Deal Desk run",
    )
    pending[session.id] = kickoff(req.rfp)
    return {"session_id": session.id, "console": f"https://platform.claude.com/sessions/{session.id}"}


@app.get("/api/runs/{session_id}/events")
async def run_events(session_id: str) -> StreamingResponse:
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async with await client.beta.sessions.events.stream(session_id) as stream:
                if message := pending.pop(session_id, None):
                    await client.beta.sessions.events.send(
                        session_id,
                        events=[{"type": "user.message", "content": [{"type": "text", "text": message}]}],
                    )
                async for event in stream:
                    await queue.put(f"data: {event.model_dump_json()}\n\n")
                    if event.type == "session.status_terminated":
                        break
                    # Idle with requires_action waits on us; any other idle is the end.
                    if event.type == "session.status_idle" and event.stop_reason.type != "requires_action":
                        break
        except Exception as exc:  # report it to the page rather than dropping the stream
            await queue.put(f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n")
        finally:
            await queue.put(None)

    async def body():
        task = asyncio.create_task(pump())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), PING_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    break
                yield item
        finally:
            task.cancel()

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/runs/{session_id}/files")
async def run_files(session_id: str) -> list[dict]:
    page = await client.beta.files.list(scope_id=session_id, betas=BETAS)
    return [{"id": f.id, "filename": f.filename, "size": f.size_bytes} for f in page.data]


@app.get("/api/files/{file_id}")
async def download(file_id: str, name: str = "download") -> Response:
    content = await client.beta.files.download(file_id)
    return Response(
        await content.read(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{Path(name).name}"'},
    )
