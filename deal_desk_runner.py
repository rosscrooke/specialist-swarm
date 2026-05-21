"""
Generator-based runner for the Deal Desk swarm.

Same logic as run_deal_desk.py, but yields event tuples instead of printing,
so a UI (e.g. app.py / Streamlit) can render them live.

Yields (kind, data) tuples:
    ("info", str)                — pre-flight messages
    ("error", str)               — fatal setup problem, generator returns after
    ("session_started", str)     — session.id
    ("thread_created", name)
    ("thread_running", name)
    ("delegate", name)
    ("reply_received", name)
    ("text", chunk)              — coordinator's streamed text
    ("tool_use", name)
    ("file_downloaded", Path)
    ("done", session_id)
"""

import os
from pathlib import Path
from typing import Any, Iterator

from anthropic import Anthropic


SUPPORTING_FILES = [
    Path("synthetic-data/past-wins.json"),
    Path("synthetic-data/product-overview.md"),
]
OUTPUT_DIR = Path("outputs")


def _load_inputs_as_context(rfp_path: Path) -> str:
    blocks = []
    for path in [rfp_path, *SUPPORTING_FILES]:
        if not path.exists():
            continue
        blocks.append(f"=====  DOCUMENT: {path.name}  =====\n{path.read_text()}")
    return "\n\n".join(blocks)


def run_deal_desk_stream(rfp_path: Path) -> Iterator[tuple[str, Any]]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        yield ("error", "ANTHROPIC_API_KEY is not set in the environment.")
        return

    coord_path = Path(".coordinator_id")
    env_path = Path(".environment_id")
    if not coord_path.exists() or not env_path.exists():
        yield (
            "error",
            "Missing .coordinator_id or .environment_id. Run "
            "setup_environment.py, create_specialists.py, upload_skills.py, "
            "and create_coordinator.py before launching the UI.",
        )
        return

    if not rfp_path.exists():
        yield ("error", f"RFP file not found: {rfp_path}")
        return

    coordinator_id = coord_path.read_text().strip()
    environment_id = env_path.read_text().strip()

    client = Anthropic()

    yield ("info", f"Loading {rfp_path.name} + supporting docs...")
    context = _load_inputs_as_context(rfp_path)

    yield ("info", f"Starting session against coordinator {coordinator_id}...")
    session = client.beta.sessions.create(
        agent=coordinator_id,
        environment_id=environment_id,
        title=f"Deal Desk — {rfp_path.stem}",
    )
    Path(".last_session_id").write_text(session.id)
    yield ("session_started", session.id)

    user_message = (
        "An RFP has just landed. Please run the standard Deal Desk process:\n"
        "1. Read the RFP yourself.\n"
        "2. Delegate to all four specialists in parallel.\n"
        "3. Synthesise their replies.\n"
        "4. Produce the final proposal response as a branded Word document "
        "if you have access to a docx skill; otherwise output the response "
        "as a structured markdown document.\n\n"
        "Specialists have their own skills attached for their respective "
        "domains. Move fast — the RFP deadline is real.\n\n"
        f"{context}"
    )

    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": user_message}],
                }
            ],
        )
        for event in stream:
            t = event.type
            if t == "session.thread_created":
                yield ("thread_created", event.agent_name)
            elif t == "session.thread_status_running":
                yield ("thread_running", getattr(event, "agent_name", "?"))
            elif t == "agent.thread_message_received":
                yield ("reply_received", event.from_agent_name)
            elif t == "agent.thread_message_sent":
                yield ("delegate", event.to_agent_name)
            elif t == "agent.message":
                for block in event.content:
                    if getattr(block, "type", None) == "text":
                        yield ("text", block.text)
            elif t == "agent.tool_use":
                yield ("tool_use", getattr(event, "name", "?"))
            elif t == "session.status_idle":
                break

    OUTPUT_DIR.mkdir(exist_ok=True)
    files = client.beta.files.list(
        scope_id=session.id,
        betas=["managed-agents-2026-04-01"],
    )
    for f in files.data:
        out_path = OUTPUT_DIR / f.filename
        content = client.beta.files.download(f.id)
        content.write_to_file(str(out_path))
        yield ("file_downloaded", out_path)

    yield ("done", session.id)
