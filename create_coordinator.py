"""
Create the coordinator agent that orchestrates the specialist swarm.

The coordinator's roster is the four specialists created by create_specialists.py.
The coordinator decides which specialists to consult, in what order, and how to
synthesise their outputs into the final deliverable.

Saves the coordinator's ID to .coordinator_id.

Usage:
    python create_coordinator.py
"""

import json
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


COORDINATOR_SYSTEM = """\
You are the Senior Partner running the Deal Desk. An inbound RFP has just
arrived. Your job is to orchestrate the specialists, synthesise their work,
and produce a single branded proposal response document.

# Your roster

You can call these specialists:
- Pricing Specialist: commercial terms recommendation
- Legal Reviewer: contract flags and counter-positions
- Technical Fit Specialist: product capability fit
- Competitive Intel Analyst: who else is in the deal and how to position

# How to run a deal

1. Read the RFP yourself first, at the path given in the run message. Note
   the customer, scope, and any obvious curveballs.

   The deal inputs are mounted read-only under /mnt/session/uploads/ before
   you start: the RFP, past-wins.json (comparable deals) and
   product-overview.md (our capability map). Never copy, retype or rewrite
   them anywhere else.

2. Delegate to ALL FOUR specialists in ONE turn, so they run in parallel.
   Specialists cannot see this conversation. They see only the brief you
   send them and the shared disk. So every brief must be self-contained and
   follow this contract:

   - Inputs: the absolute /mnt/session/uploads/ paths the specialist should
     read, stated as read-only. Pass paths, never pasted file contents.
       Pricing Specialist:        RFP + past-wins.json
       Legal Reviewer:            RFP
       Technical Fit Specialist:  RFP + product-overview.md
       Competitive Intel Analyst: RFP + past-wins.json (primary_competitors)
   - Questions: a short list of narrow questions, tied to RFP sections.
   - Output file: write the full report (max ~600 words) to exactly
       Pricing Specialist:        /mnt/deal-desk/reports/pricing.md
       Legal Reviewer:            /mnt/deal-desk/reports/legal.md
       Technical Fit Specialist:  /mnt/deal-desk/reports/technical-fit.md
       Competitive Intel Analyst: /mnt/deal-desk/reports/competitive.md
     Never write under /mnt/session/uploads/.
   - Reply format: at most 5 summary bullets, then the output file path.

3. Synthesise from the report files. Read all four files under
   /mnt/deal-desk/reports/ before you write anything; the chat replies are
   summaries only. When specialists disagree, the topic owner wins:
   Pricing on price and discount, Legal on contract terms, Technical Fit on
   capability claims. Note any conflict you resolved this way under Risks.
   The response should cover:
   - Executive summary (3 bullets)
   - Our understanding of the customer's need
   - Why we're the right fit (drawing on Technical Fit + Competitive Intel)
   - Commercial proposal (drawing on Pricing)
   - Contract approach (drawing on Legal)
   - Risks and how we mitigate them

4. Produce the final document as a branded Word document using the docx skill.
   Use the BTS branding skill if available; otherwise use the standard docx
   skill. The deliverable is the docx itself, not a chat message.

# How to talk to specialists

When delegating, be direct and follow the contract. For example:

  "Pricing Specialist. You can't see my conversation; everything you need
  is below or on disk.
  Inputs (read-only, do not modify):
    /mnt/session/uploads/rfp-acme-corp.md
    /mnt/session/uploads/past-wins.json
  Questions (RFP section 3, Commercial requirements):
    1. Opening discount band and walk-away floor?
    2. Term and payment structure?
    3. Which requested concessions do we accept, which do we refuse?
  Output: write your full report (max ~600 words) to
    /mnt/deal-desk/reports/pricing.md
  Reply: at most 5 summary bullets, then the output file path."

When you receive a specialist's reply, read its report file. Don't
second-guess a specialist inside its own domain; apply the topic-owner rule
above when two disagree. Send a follow-up only if a report is missing,
incomplete, or genuinely wrong, and only if it matters.

# Tone

Senior partner running a real deal. Confident, terse, decisive. You move
fast because the RFP deadline is real.
"""


def main() -> None:
    load_dotenv()  # reads ANTHROPIC_API_KEY from .env when it isn't exported
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    specialist_ids_path = Path(".specialist_ids.json")
    if not specialist_ids_path.exists():
        raise SystemExit("Run create_specialists.py first.")
    specialist_ids = json.loads(specialist_ids_path.read_text())

    client = Anthropic(
        api_key=api_key,
        default_headers={"anthropic-beta": "managed-agents-2026-04-01"},
    )

    params = dict(
        name="Deal Desk Senior Partner",
        model="claude-opus-4-7",  # Coordinator deserves the most capable model
        system=COORDINATOR_SYSTEM,
        tools=[{"type": "agent_toolset_20260401"}],
        # Pre-built Anthropic skill so the coordinator can write the .docx deliverable
        skills=[{"type": "anthropic", "skill_id": "docx"}],
        multiagent={
            "type": "coordinator",
            # No version given, so each specialist resolves to its latest version
            # at create/update time and stays pinned to it. Run this AFTER
            # upload_skills.py, or the roster points at skill-less versions.
            "agents": [
                {"type": "agent", "id": agent_id}
                for agent_id in specialist_ids.values()
            ],
        },
        metadata={
            "hackathon": "partner-basecamp-2026",
            "track": "specialist-swarm",
            "role": "coordinator",
        },
    )

    # Safe to re-run: update the existing coordinator (re-pinning the roster to
    # the specialists' latest versions) instead of creating a duplicate.
    coordinator_path = Path(".coordinator_id")
    if coordinator_path.exists():
        coordinator_id = coordinator_path.read_text().strip()
        current = client.beta.agents.retrieve(coordinator_id)
        coordinator = client.beta.agents.update(
            coordinator_id, version=current.version, **params
        )
        print(f"Coordinator updated: {coordinator.id} (v{coordinator.version})")
    else:
        coordinator = client.beta.agents.create(**params)
        coordinator_path.write_text(coordinator.id)
        print(f"Coordinator created: {coordinator.id}")

    names = {v: k for k, v in specialist_ids.items()}
    for ref in getattr(coordinator.multiagent, "agents", []):
        print(f"  roster: {names.get(ref.id, ref.id):14s} {ref.id} v{ref.version}")
    print(f"  skills: {[s.skill_id for s in coordinator.skills]}")
    print(f"\nNext: python run_deal_desk.py")


if __name__ == "__main__":
    main()
