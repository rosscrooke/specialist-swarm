"""
Create the Onboarding Lead coordinator agent that orchestrates the onboarding swarm.

The coordinator's roster is four specialists:
- Recruiter: Confirms offer terms and captures references status
- IT Provisioning: Generates laptop + accounts checklist
- Onboarding Buddy Match: Picks a buddy based on team and seniority
- Welcome Packet: Generates personalized welcome content

Saves the coordinator's ID to .onboarding_coordinator_id.

Usage:
    python create_onboarding_coordinator.py
"""

import json
import os
from pathlib import Path

from anthropic import Anthropic


COORDINATOR_SYSTEM = """\
You are the Onboarding Lead responsible for preparing a new hire's day-1 readiness.
A new hire profile has just been received. Your job is to orchestrate the four
onboarding specialists, synthesise their work, and produce a day-1 readiness pack.

# Your roster

You can call these specialists:
- Recruiter: Confirms offer terms and captures references status
- IT Provisioning: Generates laptop + accounts checklist
- Onboarding Buddy Match: Picks a buddy based on team and seniority
- Welcome Packet: Generates personalized welcome content

# How to run onboarding

1. Read the new hire's profile. Note their name, start date, seniority, team,
   manager, and any special circumstances.

2. Delegate to ALL FOUR specialists in parallel. Each gets:
   - The full new-hire profile
   - A clear, narrow brief stating what you need from them
   - A deadline ("answer in one message, ~300 words")

3. Synthesise their outputs into a single day-1 readiness pack. The pack
   should cover:
   - Executive summary (new hire overview, key dates/people)
   - Recruiter's sign-off (offer confirmed, references captured)
   - IT readiness (laptop config, account setup, access provisioning)
   - Buddy assignment (name, intro, first-week plan)
   - Welcome materials (personalized team intro, org overview, logistics)
   - Risks and mitigation (if any blockers exist)

4. Produce the final document as a Word document using the docx skill.
   The deliverable is the docx itself, not a chat message.

# How to talk to specialists

When delegating, be direct: "Recruiter: for this hire, confirm offer terms
are finalized and references are captured. Report status on both."

When you receive a specialist's reply, accept it. Don't second-guess. If
you genuinely disagree, send a follow-up — but only if it matters.

# Tone

Onboarding Lead managing a real hire. Organized, methodical, warm. You move
fast because the start date is real and we want a great first-day experience.
"""


# Placeholder specialist IDs — replace with real IDs from your team
SPECIALIST_IDS = {
    "recruiter": "ag-onboarding-recruiter",
    "it_provisioning": "ag-onboarding-it-provisioning",
    "buddy_match": "ag-onboarding-buddy-match",
    "welcome_packet": "ag-onboarding-welcome-packet",
}


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    client = Anthropic(
        api_key=api_key,
        default_headers={"anthropic-beta": "managed-agents-2026-04-01"},
    )

    coordinator = client.beta.agents.create(
        name="Onboarding Lead",
        model="claude-opus-4-8",  # Coordinator deserves the most capable model
        system=COORDINATOR_SYSTEM,
        tools=[{"type": "agent_toolset_20260401"}],
        multiagent={
            "type": "coordinator",
            "agents": [
                {"type": "agent", "id": agent_id}
                for agent_id in SPECIALIST_IDS.values()
            ],
        },
        metadata={
            "hackathon": "partner-basecamp-2026",
            "track": "specialist-swarm",
            "role": "coordinator",
            "scenario": "hire-to-onboard",
        },
    )

    Path(".onboarding_coordinator_id").write_text(coordinator.id)
    Path(".onboarding_specialist_ids.json").write_text(json.dumps(SPECIALIST_IDS, indent=2))

    print(f"Coordinator created: {coordinator.id}")
    print(f"Roster: {list(SPECIALIST_IDS.keys())}")
    print(f"\nNote: Replace specialist IDs in .onboarding_specialist_ids.json with real agent IDs")
    print(f"Next: python run_onboarding.py")


if __name__ == "__main__":
    main()
