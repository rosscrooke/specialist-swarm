"""
Create the onboarding specialist sub-agents (Scenario Card C — Hire-to-Onboard).

Builds two specialists that the Onboarding Lead coordinator can fan work out to:
- Recruiter        — confirms offer terms, captures references status
- IT Provisioning  — generates the laptop + accounts checklist

Each specialist gets:
- A narrow system prompt scoped to its lane
- The agent toolset (file ops, web search, web fetch, bash)

Saves the resulting agent IDs to .onboarding_specialist_ids.json so the
coordinator script can reference them.

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python create_onboarding_specialists.py
"""

import json
import os
from pathlib import Path

from anthropic import Anthropic


SPECIALISTS = [
    {
        "key": "recruiter",
        "name": "Recruiter",
        "model": "claude-sonnet-4-6",
        "system": (
            "You are the Recruiter in a Hire-to-Onboard team. Your job is to "
            "confirm the new hire's offer terms and capture the status of their "
            "references so the rest of onboarding can proceed with confidence.\n\n"
            "Inputs you'll receive:\n"
            "- The new-hire-profile.md (name, role, team, level, start date, "
            "offer details)\n\n"
            "Your output: a concise offer-and-references confirmation covering:\n"
            "1. Offer terms confirmed — title, level, team, start date, base "
            "compensation, and any signing/equity components present in the "
            "profile (flag anything missing or inconsistent)\n"
            "2. References status — for each named reference: relationship, "
            "contact status (requested / received / outstanding), and any red "
            "flags. If references aren't in the profile, say so explicitly and "
            "mark them as outstanding.\n"
            "3. Go / no-go for onboarding — a clear readiness call with the "
            "blocking items, if any.\n\n"
            "Be precise. Never invent compensation numbers or reference details "
            "that aren't in the profile — flag gaps instead of filling them."
        ),
    },
    {
        "key": "it_provisioning",
        "name": "IT Provisioning",
        "model": "claude-haiku-4-5-20251001",  # Cheaper for a structured checklist
        "system": (
            "You are the IT Provisioning specialist in a Hire-to-Onboard team. "
            "Your job is to generate the day-1 hardware and accounts checklist "
            "for a new hire.\n\n"
            "Inputs you'll receive:\n"
            "- The new-hire-profile.md (role, team, level, start date, location, "
            "remote/onsite)\n\n"
            "Your output: a provisioning checklist tailored to the role:\n"
            "1. Hardware — laptop spec appropriate to the role (e.g. engineering "
            "vs. sales vs. design), peripherals, and shipping/pickup based on "
            "location and remote/onsite status\n"
            "2. Accounts & access — email/SSO, core company apps, and the "
            "role-specific tools and access groups this person needs on day 1\n"
            "3. Security setup — MFA, device enrolment/MDM, VPN\n"
            "4. Timeline — what must be ready before the start date vs. day-1 "
            "tasks, anchored to the start date in the profile\n\n"
            "Present it as a clear, actionable checklist with owners where "
            "relevant. Tailor hardware and access to the specific role — don't "
            "hand out a generic list."
        ),
    },
]


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    client = Anthropic(
        api_key=api_key,
        default_headers={"anthropic-beta": "managed-agents-2026-04-01"},
    )

    specialist_ids: dict[str, str] = {}
    for spec in SPECIALISTS:
        agent = client.beta.agents.create(
            name=spec["name"],
            model=spec["model"],
            system=spec["system"],
            tools=[{"type": "agent_toolset_20260401"}],
            metadata={
                "hackathon": "partner-basecamp-2026",
                "track": "specialist-swarm",
                "scenario": "hire-to-onboard",
                "role": spec["key"],
            },
        )
        specialist_ids[spec["key"]] = agent.id
        print(f"  Created {spec['name']:20s} -> {agent.id}")

    Path(".onboarding_specialist_ids.json").write_text(
        json.dumps(specialist_ids, indent=2)
    )
    print(
        f"\nSaved {len(specialist_ids)} specialist IDs to "
        ".onboarding_specialist_ids.json"
    )


if __name__ == "__main__":
    main()
