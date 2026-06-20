"""
Run the Onboarding swarm against the new-hire profile.

Loads the new-hire-profile.md and supporting files, creates a session with
the Onboarding Lead coordinator, streams events as the swarm processes the
hire in parallel, and produces the day-1 readiness pack as a Word document.

Saves the transcript and all deliverables to outputs/.

Usage:
    python run_onboarding.py
"""

import os
from pathlib import Path

from anthropic import Anthropic


PROFILE_PATH = Path("synthetic-data/new-hire-profile.md")
OUTPUT_DIR = Path("outputs")


def load_profile() -> str:
    if not PROFILE_PATH.exists():
        raise SystemExit(f"Missing {PROFILE_PATH}")
    print(f"  Loading {PROFILE_PATH.name}")
    return PROFILE_PATH.read_text()


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    if not Path(".onboarding_coordinator_id").exists():
        raise SystemExit(
            "Missing .onboarding_coordinator_id. Run "
            "create_onboarding_coordinator.py first."
        )

    if not Path(".environment_id").exists():
        raise SystemExit(
            "Missing .environment_id. Run setup_environment.py first."
        )

    coordinator_id = Path(".onboarding_coordinator_id").read_text().strip()
    environment_id = Path(".environment_id").read_text().strip()

    client = Anthropic()

    print("Loading new-hire profile...")
    profile = load_profile()

    print(f"\nStarting session against coordinator {coordinator_id}...")
    session = client.beta.sessions.create(
        agent=coordinator_id,
        environment_id=environment_id,
        title="Onboarding — New Hire",
    )
    Path(".last_onboarding_session_id").write_text(session.id)

    user_message = (
        "A new hire is starting soon. Please run the standard onboarding process:\n"
        "1. Read the new-hire profile yourself.\n"
        "2. Delegate to all four specialists in parallel:\n"
        "   - Recruiter: Confirm offer terms and references status\n"
        "   - IT Provisioning: Generate laptop + accounts checklist\n"
        "   - Buddy Match: Select and brief the buddy\n"
        "   - Welcome Packet: Create personalized welcome materials\n"
        "3. Synthesise their replies into a coherent day-1 readiness pack.\n"
        "4. Produce the final pack as a Word document using the docx skill.\n\n"
        "Move fast — the start date is real. We want them to have a great "
        "first day.\n\n"
        f"{profile}"
    )

    # Stream the events — watch for parallel thread spawns.
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
    transcript_path = OUTPUT_DIR / "onboarding-transcript.txt"
    transcript_path.write_text("".join(final_text_parts))
    print(f"\nCoordinator transcript saved to {transcript_path}")

    # Pull every file the agents produced in the container
    print("\nDownloading deliverables from the session container...")
    files = client.beta.files.list(
        scope_id=session.id,
        betas=["managed-agents-2026-04-01"],
    )
    file_count = 0
    for f in files.data:
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
