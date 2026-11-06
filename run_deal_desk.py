"""
Run the Deal Desk swarm against the synthetic RFP.

Uploads the RFP + past-wins + product-overview with the Files API and mounts
them read-only into the session at /mnt/session/uploads/. Every agent thread
shares that disk, so the coordinator hands specialists file paths instead of
pasted text. Streams events as they come in so you can watch the parallel
thread fan-out — this is the demo, narrate it live.

Saves the final transcript to outputs/.

Usage:
    python run_deal_desk.py
"""

import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


RFP_PATH = Path("synthetic-data/rfp-acme-corp.md")
SUPPORTING_FILES = [
    Path("synthetic-data/past-wins.json"),
    Path("synthetic-data/product-overview.md"),
]
INPUT_FILES = [RFP_PATH, *SUPPORTING_FILES]
OUTPUT_DIR = Path("outputs")

# A file mounted with mount_path "/name.ext" appears here inside the container.
UPLOADS_DIR = "/mnt/session/uploads"
# Originals only need to outlive session creation; the session keeps its own copy.
UPLOAD_TTL_SECONDS = 86_400


def container_path(path: Path) -> str:
    return f"{UPLOADS_DIR}/{path.name}"


def upload_inputs(client: Anthropic) -> list[dict]:
    """Upload each input file and return session `resources` that mount it."""
    missing = [str(p) for p in INPUT_FILES if not p.exists()]
    if missing:
        raise SystemExit(f"Missing input file(s): {', '.join(missing)}")

    resources = []
    for path in INPUT_FILES:
        uploaded = client.files.upload(
            file=(path.name, path.read_bytes(), "text/plain"),
            expires_in_seconds=UPLOAD_TTL_SECONDS,
        )
        print(f"  uploaded {path.name:24s} -> {uploaded.id}")
        resources.append(
            {"type": "file", "file_id": uploaded.id, "mount_path": f"/{path.name}"}
        )
    return resources


def main() -> None:
    load_dotenv()  # reads ANTHROPIC_API_KEY from .env when it isn't exported
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    if not Path(".coordinator_id").exists() or not Path(".environment_id").exists():
        raise SystemExit(
            "Missing .coordinator_id or .environment_id. Run "
            "create_specialists.py, upload_skills.py, then create_coordinator.py first."
        )

    coordinator_id = Path(".coordinator_id").read_text().strip()
    environment_id = Path(".environment_id").read_text().strip()

    client = Anthropic()

    print("Uploading RFP + supporting docs...")
    resources = upload_inputs(client)

    print(f"\nStarting session against coordinator {coordinator_id}...")
    session = client.beta.sessions.create(
        agent=coordinator_id,
        environment_id=environment_id,
        title="Deal Desk — Acme Corp RFP",
        resources=resources,
    )
    Path(".last_session_id").write_text(session.id)

    mounted_file_ids = set()
    for r in session.resources or []:
        if getattr(r, "type", None) == "file":
            mounted_file_ids.add(r.file_id)
            print(f"  mounted {r.mount_path:24s} ({r.file_id})")

    user_message = (
        "An RFP has just landed. The inputs are already on the shared disk, "
        "mounted read-only:\n"
        f"- RFP: {container_path(RFP_PATH)}\n"
        f"- Comparable past deals: {container_path(SUPPORTING_FILES[0])}\n"
        f"- Product capability map: {container_path(SUPPORTING_FILES[1])}\n\n"
        "Please run the standard Deal Desk process:\n"
        "1. Read the RFP at the path above.\n"
        "2. Delegate to all four specialists in one turn, following the "
        "delegation contract: pass file paths, not file contents.\n"
        "3. Synthesise from the specialists' report files.\n"
        "4. Produce the final proposal response as a branded Word document "
        "if you have access to a docx skill; otherwise output the response "
        "as a structured markdown document.\n\n"
        "Specialists have their own skills attached for their respective "
        "domains. Move fast — the RFP deadline is real."
    )

    # Stream the events — this is the demo. Watch for parallel thread spawns.
    print("\n=== EVENT STREAM (this is the demo) ===\n")
    final_text_parts: list[str] = []

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
                print(f"  [thread spawned]   {event.agent_name}", flush=True)
            elif t == "session.thread_status_running":
                name = getattr(event, "agent_name", "?")
                print(f"  [thread running]   {name}", flush=True)
            elif t == "agent.thread_message_received":
                print(f"  [reply ←]          {event.from_agent_name}", flush=True)
            elif t == "agent.thread_message_sent":
                print(f"  [delegate →]       {event.to_agent_name}", flush=True)
            elif t == "agent.message":
                for block in event.content:
                    if getattr(block, "type", None) == "text":
                        final_text_parts.append(block.text)
                        print(block.text, end="", flush=True)
            elif t == "agent.tool_use":
                print(f"\n  [tool: {getattr(event, 'name', '?')}]", flush=True)
            elif t == "session.status_idle":
                print("\n\n[swarm finished]")
                break

    OUTPUT_DIR.mkdir(exist_ok=True)
    transcript_path = OUTPUT_DIR / "coordinator-transcript.txt"
    transcript_path.write_text("".join(final_text_parts))
    print(f"\nCoordinator transcript saved to {transcript_path}")

    # Pull every file the agents produced in the container
    print("\nDownloading deliverables from the session container...")
    files = client.beta.files.list(
        scope_id=session.id,
        betas=["managed-agents-2026-04-01"],
    )
    input_names = {p.name for p in INPUT_FILES}
    file_count = 0
    for f in files.data:
        if f.id in mounted_file_ids or f.filename in input_names:
            continue  # our own inputs, mounted at session creation
        out_path = OUTPUT_DIR / f.filename
        print(f"  {f.filename}  ->  {out_path}")
        content = client.beta.files.download(f.id)
        content.write_to_file(str(out_path))
        file_count += 1

    if file_count == 0:
        print("  (no files found — agents may have produced text-only output)")
    else:
        print(f"\nDownloaded {file_count} file(s) to {OUTPUT_DIR}/")

    print(f"\nView the full session (including all sub-agent threads) at:")
    print(f"  https://platform.claude.com/sessions/{session.id}")


if __name__ == "__main__":
    main()
