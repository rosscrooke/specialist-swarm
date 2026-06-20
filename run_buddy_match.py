"""
Onboarding Buddy Match — standalone specialist runner (Card C).

Demos a single specialist in isolation: it creates (or reuses) the Onboarding
Buddy Match agent, uploads + attaches its buddy-match-playbook skill, feeds it the
new-hire profile + buddy roster, and prints the recommended buddy.

No coordinator and no other Card C specialists are required — a session can run
directly against a single agent. Card A (Deal Desk) files are untouched.

Patterns reused from the Deal Desk swarm:
- agent creation        -> create_specialists.py
- skill upload + attach -> upload_skills.py (idempotent)
- session event stream  -> run_deal_desk.py

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python setup_environment.py     # reused as-is; creates/uses .environment_id
    python run_buddy_match.py
"""

import os
from pathlib import Path

from anthropic import Anthropic
from anthropic.lib import files_from_dir


BETA = "managed-agents-2026-04-01"

NEW_HIRE_PATH = Path("synthetic-data/buddy-match-new-hire.md")
ROSTER_PATH = Path("synthetic-data/buddy-roster.json")
SKILL_DIR = Path("skills/buddy-match-playbook")
OUTPUT_DIR = Path("outputs")
AGENT_ID_PATH = Path(".buddy_match_id")

SPECIALIST_NAME = "Onboarding Buddy Match"
SPECIALIST_MODEL = "claude-sonnet-4-6"  # bounded reasoning task, like the other lane specialists
SPECIALIST_SYSTEM = (
    "You are the Onboarding Buddy Match specialist in a Hire-to-Onboard swarm. "
    "Your job is to pick the single best onboarding buddy for a new hire from a "
    "candidate roster.\n\n"
    "Inputs you'll receive:\n"
    "- new-hire-profile.md (the new hire: team, seniority level, start date, "
    "location/timezone, languages, interests)\n"
    "- buddy-roster.json (candidate buddies with team, seniority_level, tenure, "
    "capacity, leave status, timezone, languages, interests, prior rating)\n"
    "- The buddy-match-playbook skill — your authoritative matching method.\n\n"
    "Method: ALWAYS follow the buddy-match-playbook skill. Apply its hard "
    "eligibility filters first, then weight TEAM and SENIORITY as the primary "
    "signals, and only use timezone / language / interests / rating as tiebreakers. "
    "Return exactly the output format the skill specifies: one recommended buddy "
    "with rationale, one backup, the excluded candidates with reasons, and any flag. "
    "Be decisive — recommend one buddy, not a shortlist."
)


def load_inputs_as_context() -> str:
    blocks = []
    for path in [NEW_HIRE_PATH, ROSTER_PATH]:
        if not path.exists():
            print(f"  WARNING: {path} missing — skipping")
            continue
        print(f"  including {path.name}")
        blocks.append(f"=====  DOCUMENT: {path.name}  =====\n{path.read_text()}")
    return "\n\n".join(blocks)


def create_or_reuse_specialist(client: Anthropic) -> str:
    """Create the buddy-match specialist, or reuse the saved id on rerun."""
    if AGENT_ID_PATH.exists():
        agent_id = AGENT_ID_PATH.read_text().strip()
        print(f"Reusing existing specialist: {agent_id}")
        return agent_id

    agent = client.beta.agents.create(
        name=SPECIALIST_NAME,
        model=SPECIALIST_MODEL,
        system=SPECIALIST_SYSTEM,
        tools=[{"type": "agent_toolset_20260401"}],
        metadata={
            "hackathon": "partner-basecamp-2026",
            "track": "specialist-swarm",
            "card": "C-hire-to-onboard",
            "role": "buddy_match",
        },
    )
    AGENT_ID_PATH.write_text(agent.id)
    print(f"Created {SPECIALIST_NAME} -> {agent.id}")
    return agent.id


def upload_and_attach_skill(client: Anthropic, specialist_id: str) -> None:
    """Idempotently upload the buddy-match-playbook skill and attach it.

    Mirrors upload_skills.py: Skills API enforces unique display_title, so we
    reuse an existing skill with the same title rather than re-uploading, and we
    only attach if it isn't already on the agent.
    """
    if not (SKILL_DIR / "SKILL.md").exists():
        raise SystemExit(f"Missing {SKILL_DIR}/SKILL.md")

    display_title = SKILL_DIR.name.replace("-", " ").title()

    existing_by_title: dict[str, str] = {}
    for page in client.beta.skills.list(source="custom"):
        existing_by_title[page.display_title] = page.id

    if display_title in existing_by_title:
        skill_id = existing_by_title[display_title]
        print(f"Reusing existing skill: {SKILL_DIR.name} ({skill_id})")
    else:
        print(f"Uploading skill: {SKILL_DIR.name}...")
        skill = client.beta.skills.create(
            display_title=display_title,
            files=files_from_dir(str(SKILL_DIR)),
        )
        skill_id = skill.id
        print(f"  -> {skill_id}")

    current = client.beta.agents.retrieve(specialist_id)
    already_attached = any(
        s.get("skill_id") == skill_id for s in (current.skills or [])
    )
    if already_attached:
        print("  skill already attached ✓")
        return

    new_skills = list(current.skills or []) + [
        {"type": "custom", "skill_id": skill_id, "version": "latest"}
    ]
    client.beta.agents.update(
        specialist_id,
        version=current.version,
        skills=new_skills,
    )
    print("  attached ✓")


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    if not Path(".environment_id").exists():
        raise SystemExit(
            "Missing .environment_id. Run `python setup_environment.py` first."
        )
    environment_id = Path(".environment_id").read_text().strip()

    client = Anthropic(default_headers={"anthropic-beta": BETA})

    specialist_id = create_or_reuse_specialist(client)
    upload_and_attach_skill(client, specialist_id)

    print("\nLoading new-hire profile + buddy roster...")
    context = load_inputs_as_context()

    print(f"\nStarting session against specialist {specialist_id}...")
    session = client.beta.sessions.create(
        agent=specialist_id,
        environment_id=environment_id,
        title="Buddy Match — Markus Vogel",
    )
    Path(".last_buddy_session_id").write_text(session.id)

    user_message = (
        "A new hire is starting soon. Using your buddy-match-playbook skill, pick "
        "the single best onboarding buddy from the roster.\n"
        "1. Apply the hard eligibility filters first.\n"
        "2. Score the survivors on team and seniority (the primary signals).\n"
        "3. Break any near-ties on timezone / language / interests / rating.\n"
        "4. Reply in exactly the skill's output format: recommended buddy + why, "
        "a backup, the excluded candidates with reasons, and any flag.\n\n"
        f"{context}"
    )

    print("\n=== EVENT STREAM ===\n")
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
            if t == "session.thread_status_running":
                print(f"  [running]   {getattr(event, 'agent_name', '?')}", flush=True)
            elif t == "agent.message":
                for block in event.content:
                    if getattr(block, "type", None) == "text":
                        final_text_parts.append(block.text)
                        print(block.text, end="", flush=True)
            elif t == "agent.tool_use":
                print(f"\n  [tool: {getattr(event, 'name', '?')}]", flush=True)
            elif t == "session.status_idle":
                print("\n\n[match finished]")
                break

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / "buddy-match.md"
    out_path.write_text("".join(final_text_parts))
    print(f"\nMatch saved to {out_path}")

    # Pull any files the specialist produced in the container.
    print("\nDownloading any deliverables from the session container...")
    files = client.beta.files.list(scope_id=session.id, betas=[BETA])
    file_count = 0
    for f in files.data:
        dest = OUTPUT_DIR / f.filename
        print(f"  {f.filename}  ->  {dest}")
        client.beta.files.download(f.id).write_to_file(str(dest))
        file_count += 1
    if file_count == 0:
        print("  (no container files — text output only)")

    print(f"\nView the full session at:")
    print(f"  https://platform.claude.com/sessions/{session.id}")


if __name__ == "__main__":
    main()
