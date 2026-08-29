"""
Run the Godot scene swarm, then hold its output to a real engine.

This is the demo. Two things are worth narrating while it runs:

  1. The event stream — five threads spawning in parallel, reports flowing
     back to the coordinator. That is the architecture pitch.
  2. The verification gate — a local Godot 4.7 install importing,
     instantiating and booting what the swarm just wrote, and the swarm
     repairing itself from the engine's actual error output. That is the
     difference between a demo and a deliverable.

Usage:
    python run_scene_build.py
    python run_scene_build.py --max-rounds 5 --brief path/to/brief.md
    python run_scene_build.py --budget-usd 10
"""

from __future__ import annotations

import _thread
import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

import godot_verify
from godot_verify import PROTECTED_FILES

load_dotenv()

# The event stream is the demo. Python block-buffers stdout when it is piped
# or redirected, which would hold the whole fan-out back until the run ends.
sys.stdout.reconfigure(line_buffering=True)

DEFAULT_BRIEF = Path("synthetic-data/level-brief-crystal-caverns.md")
PROJECT_DIR = Path("godot_project")
OUTPUT_DIR = Path("outputs")
MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"

# Files the swarm is allowed to place in the project. Anything else it writes
# is reported and ignored — a stray README in the project directory is
# harmless, but a stray project.godot would silently break the input contract.
ALLOWED_SUFFIXES = (".tscn", ".gd", ".tres")


def reset_project() -> None:
    """
    Clear everything the swarm generated, keeping only the harness-owned
    files. Without this, a run that produces nothing inherits the previous
    run's working scene and reports a false pass.
    """
    PROJECT_DIR.mkdir(exist_ok=True)
    removed = 0
    for path in PROJECT_DIR.iterdir():
        if path.name in PROTECTED_FILES:
            continue
        if path.is_dir():
            if path.name == ".godot":
                shutil.rmtree(path)
            continue
        path.unlink()
        removed += 1
    if removed:
        print(f"  cleared {removed} file(s) from {PROJECT_DIR}/")


def stream_turn(
    client: Anthropic,
    session_id: str,
    message: str,
    idle_timeout: float = 90.0,
) -> str:
    """
    Send one message and stream until the session goes idle.

    Two failure modes, both hit in practice, both handled here:

    1. **Nothing is ever sent.** The documented advice is "open the stream,
       then send", but the Python SDK's stream blocks in __enter__ until the
       first event arrives — and with nothing sent, none ever does. So the
       message goes out on a BACKGROUND THREAD: correct whether or not
       __enter__ blocks, and it misses no events either way.

    2. **The stream stalls mid-turn.** SSE has no replay, so a dropped
       connection leaves the consumer waiting on a session that has already
       finished. A rolling WATCHDOG therefore reconciles against the server
       whenever the stream goes quiet: if the session is genuinely still
       running, keep waiting; if it has gone idle, stop.

    Silence is never treated as progress.
    """
    parts: list[str] = []
    send_failure: list[BaseException] = []
    last_event_at = [time.monotonic()]
    finished = threading.Event()

    def _send() -> None:
        try:
            client.beta.sessions.events.send(
                session_id,
                events=[{"type": "user.message", "content": [{"type": "text", "text": message}]}],
            )
        except BaseException as exc:
            send_failure.append(exc)
            finished.set()
            _thread.interrupt_main()

    def _watchdog() -> None:
        while not finished.wait(5.0):
            quiet_for = time.monotonic() - last_event_at[0]
            if quiet_for < idle_timeout:
                continue
            try:
                status = client.beta.sessions.retrieve(session_id).status
            except Exception:
                continue  # transient; try again next tick
            if status in ("idle", "terminated"):
                print(
                    f"\n  [watchdog] stream quiet {quiet_for:.0f}s and the session is "
                    f"'{status}' — the turn is done; the stream stalled.",
                    flush=True,
                )
                finished.set()
                _thread.interrupt_main()
                return
            last_event_at[0] = time.monotonic()  # genuinely still working

    threading.Thread(target=_send, daemon=True).start()
    threading.Thread(target=_watchdog, daemon=True).start()

    try:
        with client.beta.sessions.events.stream(session_id) as stream:
            for event in stream:
                last_event_at[0] = time.monotonic()
                kind = event.type
                if kind == "session.thread_created":
                    print(f"  [thread spawned]  {getattr(event, 'agent_name', '?')}", flush=True)
                elif kind == "session.thread_status_running":
                    print(f"  [running]         {getattr(event, 'agent_name', '?')}", flush=True)
                elif kind == "session.thread_status_idle":
                    print(f"  [thread idle]     {getattr(event, 'agent_name', '?')}", flush=True)
                elif kind == "agent.thread_message_sent":
                    print(f"  [delegate ->]     {getattr(event, 'to_agent_name', '?')}", flush=True)
                elif kind == "agent.thread_message_received":
                    print(f"  [reply <-]        {getattr(event, 'from_agent_name', '?')}", flush=True)
                elif kind == "agent.tool_use":
                    print(f"  [tool]            {getattr(event, 'name', '?')}", flush=True)
                elif kind == "agent.thinking":
                    print("  [thinking...]", flush=True)
                elif kind == "agent.message":
                    for block in event.content:
                        if getattr(block, "type", None) == "text":
                            parts.append(block.text)
                            print(block.text, end="", flush=True)
                elif kind == "session.error":
                    print(f"\n  [SESSION ERROR]   {event}", flush=True)
                elif kind == "session.status_idle":
                    stop_reason = getattr(event, "stop_reason", None)
                    print(f"\n  [idle] stop_reason={stop_reason}\n", flush=True)
                    if stop_reason == "budget_reached":
                        finished.set()
                        raise SystemExit(
                            "Session hit its budget cap. Re-run with a higher "
                            "--budget-usd and --resume-session last to continue."
                        )
                    break
    except KeyboardInterrupt:
        pass  # watchdog decided the turn is over
    finally:
        finished.set()

    if send_failure:
        raise SystemExit(f"Failed to send the message: {send_failure[0]}") from send_failure[0]
    return "".join(parts)


def download_outputs(client: Anthropic, session_id: str) -> list[str]:
    """
    Pull everything the agents wrote to /mnt/session/outputs/ into the project.

    Files are indexed a second or two after the session goes idle, so this
    retries briefly before concluding the swarm produced nothing.
    """
    files = []
    for attempt in range(4):
        listing = client.beta.files.list(scope_id=session_id, betas=[MANAGED_AGENTS_BETA])
        files = list(listing.data)
        if files:
            break
        time.sleep(2)

    if not files:
        print("  no output files found — the swarm wrote nothing this round")
        return []

    # Later rounds re-emit the same filenames; apply oldest first so the most
    # recent version of each file wins.
    files.sort(key=lambda f: getattr(f, "created_at", "") or "")

    written: list[str] = []
    for file_obj in files:
        name = Path(file_obj.filename).name  # flatten defensively
        if name in PROTECTED_FILES:
            print(f"  refused  {name}  (harness-owned, ignored)")
            continue
        if not name.endswith(ALLOWED_SUFFIXES):
            print(f"  skipped  {name}  (not a scene or script)")
            continue
        content = client.beta.files.download(file_obj.id)
        content.write_to_file(str(PROJECT_DIR / name))
        print(f"  wrote    {name}")
        written.append(name)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Godot scene swarm with local verification.")
    parser.add_argument("--brief", type=Path, default=DEFAULT_BRIEF)
    parser.add_argument("--max-rounds", type=int, default=3, help="repair rounds after the build")
    parser.add_argument("--budget-usd", type=float, default=5.0, help="hard session spend cap")
    parser.add_argument("--keep-project", action="store_true", help="do not clear godot_project first")
    parser.add_argument(
        "--resume-session",
        metavar="SESSION_ID",
        help=(
            "Attach to an existing session instead of building from scratch: skip "
            "round 0 and go straight to download -> verify -> repair, keeping every "
            "thread's context. Pass 'last' to reuse .last_session_id."
        ),
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY (or put it in .env) before running.")
    for required in (Path(".coordinator_id"), Path(".environment_id")):
        if not required.exists():
            raise SystemExit(
                f"Missing {required}. Run setup_environment.py, create_specialists.py, "
                "upload_skills.py, then create_coordinator.py first."
            )
    if not args.brief.exists():
        raise SystemExit(f"Brief not found: {args.brief}")

    coordinator_id = Path(".coordinator_id").read_text().strip()
    environment_id = Path(".environment_id").read_text().strip()
    brief = args.brief.read_text()

    # Fail early on a missing engine rather than after paying for a build.
    godot_bin = godot_verify.find_godot()
    print(f"Godot binary: {godot_bin}")

    if not args.keep_project:
        reset_project()

    client = Anthropic()

    if args.resume_session:
        session_id = args.resume_session
        if session_id == "last":
            last = Path(".last_session_id")
            if not last.exists():
                raise SystemExit("No .last_session_id to resume from.")
            session_id = last.read_text().strip()

        existing = client.beta.sessions.retrieve(session_id)
        spent_obj = getattr(getattr(existing, "usage", None), "list_cost", None)
        spent_cents = int(spent_obj.amount) if spent_obj else 0
        print(f"Resuming {session_id}  (status {existing.status}, spent ${spent_cents / 100:.2f})")

        # A budget can be CHANGED but never added to a session created without
        # one, nor re-added once removed, and the new cap must exceed what has
        # already been spent. So treat raising it as best-effort, not a
        # precondition for resuming.
        target_cents = int(args.budget_usd * 100)
        if getattr(existing, "budget", None) is None:
            print("  no budget on this session — one cannot be added after creation")
        elif target_cents <= spent_cents:
            print(f"  --budget-usd ${args.budget_usd:.2f} is under the ${spent_cents / 100:.2f} "
                  f"already spent; keeping the existing cap")
        else:
            client.beta.sessions.update(
                session_id,
                budget={"type": "limit",
                        "max_list_cost": {"amount": str(target_cents), "currency": "USD"}},
            )
            print(f"  budget raised to ${args.budget_usd:.2f}")

        print(f"Watch it live: https://platform.claude.com/sessions/{session_id}\n")
        print("-- downloading what the session has already produced --")
        download_outputs(client, session_id)
        return verify_and_repair(client, session_id, args, godot_bin)

    session = client.beta.sessions.create(
        agent=coordinator_id,
        environment_id=environment_id,
        title="Godot scene swarm — 2D platformer",
        budget={
            "type": "limit",
            "max_list_cost": {"amount": str(int(args.budget_usd * 100)), "currency": "USD"},
        },
    )
    Path(".last_session_id").write_text(session.id)
    print(f"Session: {session.id}   (budget ${args.budget_usd:.2f})")
    print(f"Watch it live: https://platform.claude.com/sessions/{session.id}\n")

    build_message = (
        "Build the Godot 4.7 scene described in the brief below.\n\n"
        "Run your standard process: delegate to the three builders in a single "
        "message so they work in parallel, then have the Scene Integrator "
        "assemble main.tscn. Every file goes to /mnt/session/outputs/.\n\n"
        "A local Godot 4.7 engine will verify your output the moment you finish, "
        "so correctness of the .tscn text format matters more than ambition.\n\n"
        "===== LEVEL BRIEF =====\n"
        f"{brief}"
    )

    print("=" * 62)
    print("ROUND 0 — BUILD")
    print("=" * 62)
    stream_turn(client, session.id, build_message)

    print("-- downloading deliverables --")
    download_outputs(client, session.id)
    return verify_and_repair(client, session.id, args, godot_bin)


def verify_and_repair(client: Anthropic, session_id: str, args, godot_bin: str) -> int:
    """
    Hold whatever is in the project up to the engine, and hand any findings
    back to the swarm.

    Shared by a fresh build and a resumed session. Resuming is the cheap path:
    the container still holds the files and every thread keeps its context, so
    the specialists remember what they wrote rather than starting over.
    """
    # Verify once after the build, then up to --max-rounds repair attempts,
    # verifying again after each. So max_rounds=3 means at most 3 repairs and
    # 4 trips through the engine.
    report = None
    for attempt in range(args.max_rounds + 1):
        print("\n" + "=" * 62)
        print(f"VERIFY (after round {attempt}) — local Godot")
        print("=" * 62)
        report = godot_verify.verify(PROJECT_DIR)
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / "verify-report.json").write_text(json.dumps(report.to_dict(), indent=2))

        if report.ok:
            print("PASS — the scene imports, instantiates and boots cleanly.")
            break

        print(f"FAIL — {len(report.findings)} finding(s):")
        for finding in report.findings:
            print(f"  {finding}")

        if attempt == args.max_rounds:
            print(f"\nOut of repair rounds ({args.max_rounds}).")
            break

        print("\n" + "=" * 62)
        print(f"ROUND {attempt + 1} — REPAIR")
        print("=" * 62)
        stream_turn(client, session_id, godot_verify.format_for_swarm(report))
        print("-- downloading deliverables --")
        download_outputs(client, session_id)

    print("\n" + "=" * 62)
    if report and report.ok:
        print("RESULT: PASS")
        print(f"\nOpen it:\n  {godot_bin} --path {PROJECT_DIR.resolve()}")
    else:
        print("RESULT: FAIL — see outputs/verify-report.json")
    print(f"\nFull session (all threads): https://platform.claude.com/sessions/{session_id}")
    return 0 if (report and report.ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
