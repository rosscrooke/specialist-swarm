"""Request a specialist route and stream the coordinator session.

Usage:
    python run_swarm.py "Ferry Building" "Golden Gate Park" \\
        --specialist scenic_route
"""

import argparse
import os
from pathlib import Path

from anthropic import Anthropic


OUTPUT_DIR = Path("outputs")
SPECIALIST_CHOICES = (
    "fitness_coach",
    "scenic_route",
    "traffic_avoider",
    "cost_effective",
    "bar_crawl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan a 5:00 PM San Francisco route with one specialist."
    )
    parser.add_argument("origin", help="Starting location in the San Francisco area.")
    parser.add_argument("destination", help="Destination in the San Francisco area.")
    parser.add_argument(
        "--specialist",
        required=True,
        choices=SPECIALIST_CHOICES,
        help="Route objective to optimize.",
    )
    parser.add_argument(
        "--constraints",
        help="Optional needs such as accessibility, transport mode, or time limit.",
    )
    parser.add_argument(
        "--context",
        type=Path,
        help="Optional text file containing additional route context.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    coordinator_path = Path(".coordinator_id")
    environment_path = Path(".environment_id")
    if not coordinator_path.exists() or not environment_path.exists():
        raise SystemExit(
            "Missing .coordinator_id or .environment_id. Run "
            "setup_environment.py, create_specialists.py, and "
            "create_coordinator.py first."
        )

    task_lines = [
        "Plan this route:",
        f"Origin: {args.origin}",
        f"Destination: {args.destination}",
        f"Selected specialist: {args.specialist}",
        "Departure: 5:00 PM America/Los_Angeles",
    ]
    if args.constraints:
        task_lines.append(f"User constraints: {args.constraints}")
    task = "\n".join(task_lines)
    if args.context:
        task += f"\n\n===== CONTEXT: {args.context.name} =====\n{args.context.read_text()}"

    coordinator_id = coordinator_path.read_text().strip()
    environment_id = environment_path.read_text().strip()
    client = Anthropic()

    print(f"Starting session against coordinator {coordinator_id}...")
    session = client.beta.sessions.create(
        agent=coordinator_id,
        environment_id=environment_id,
        title=f"{args.specialist}: {args.origin[:24]} to {args.destination[:24]}",
    )
    Path(".last_session_id").write_text(session.id)

    print("\n=== EVENT STREAM ===\n")
    final_text_parts: list[str] = []

    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": task}],
                }
            ],
        )
        for event in stream:
            event_type = event.type
            if event_type == "session.thread_created":
                print(f"  [thread spawned]   {event.agent_name}", flush=True)
            elif event_type == "session.thread_status_running":
                name = getattr(event, "agent_name", "?")
                print(f"  [thread running]   {name}", flush=True)
            elif event_type == "agent.thread_message_received":
                print(f"  [reply <-]          {event.from_agent_name}", flush=True)
            elif event_type == "agent.thread_message_sent":
                print(f"  [delegate ->]       {event.to_agent_name}", flush=True)
            elif event_type == "agent.message":
                for block in event.content:
                    if getattr(block, "type", None) == "text":
                        final_text_parts.append(block.text)
                        print(block.text, end="", flush=True)
            elif event_type == "agent.tool_use":
                print(f"\n  [tool: {getattr(event, 'name', '?')}]", flush=True)
            elif event_type == "session.status_idle":
                print("\n\n[swarm finished]")
                break

    OUTPUT_DIR.mkdir(exist_ok=True)
    transcript_path = OUTPUT_DIR / "coordinator-transcript.txt"
    transcript_path.write_text("".join(final_text_parts))
    print(f"\nCoordinator transcript saved to {transcript_path}")

    print("\nDownloading session files...")
    files = client.beta.files.list(
        scope_id=session.id,
        betas=["managed-agents-2026-04-01"],
    )
    file_count = 0
    for file in files.data:
        output_path = OUTPUT_DIR / file.filename
        print(f"  {file.filename} -> {output_path}")
        content = client.beta.files.download(file.id)
        content.write_to_file(str(output_path))
        file_count += 1

    if file_count == 0:
        print("  (no files found)")
    else:
        print(f"\nDownloaded {file_count} file(s) to {OUTPUT_DIR}/")

    print("\nView the full session at:")
    print(f"  https://platform.claude.com/sessions/{session.id}")


if __name__ == "__main__":
    main()
