"""
Create four specialist sub-agents for the Deal Desk swarm.

Each specialist gets:
- A narrow system prompt
- The agent toolset (file ops, web search, web fetch, bash)
- A skill that matches its domain (uploaded separately by upload_skills.py)

Saves the resulting agent IDs to .specialist_ids.json so create_coordinator.py
can reference them.

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python create_specialists.py
"""

import json
import os
import sys
from pathlib import Path

from anthropic import Anthropic

sys.path.insert(0, str(Path(__file__).resolve().parent / "crm-mcp"))
from custom_tool import CRM_TOOLS  # noqa: E402  (synthetic CRM, custom-tool variant)


SPECIALISTS = [
    {
        "key": "pricing",
        "name": "Pricing Specialist",
        "model": "claude-sonnet-4-6",
        "system": (
            "You are the Pricing Specialist in a Deal Desk. Your job is to "
            "recommend commercial terms for inbound RFPs.\n\n"
            "Inputs you'll receive:\n"
            "- The RFP text\n"
            "- The pricing-playbook skill (your authoritative pricing rules)\n"
            "- CRM tools search_past_deals and get_deal (comparable past deals; "
            "query them yourself, nothing is pasted for you)\n\n"
            "Your output: a one-page commercial recommendation covering:\n"
            "1. List price + recommended discount band\n"
            "2. Term and payment structure\n"
            "3. Any commercial concessions you'd accept and which you'd refuse\n"
            "4. Risks to the margin\n\n"
            "Be specific about numbers. Before recommending a discount, query "
            "the CRM for comparable deals (industry, size, competitors) and cite "
            "the customers you used."
        ),
    },
    {
        "key": "legal",
        "name": "Legal Reviewer",
        "model": "claude-sonnet-4-6",
        "system": (
            "You are the Legal Reviewer in a Deal Desk. Your job is to read "
            "an RFP and flag every clause that conflicts with our standard "
            "negotiation positions.\n\n"
            "Inputs you'll receive:\n"
            "- The RFP text\n"
            "- The legal-checklist skill (your authoritative position library)\n\n"
            "Your output: a structured list of flags, each with:\n"
            "1. The RFP requirement\n"
            "2. Why it conflicts with our standard\n"
            "3. Our recommended counter-position\n"
            "4. Severity: blocker / negotiable / acceptable\n\n"
            "Be precise. Don't flag boilerplate just because it's there — "
            "only call out things that genuinely deviate from our checklist."
        ),
    },
    {
        "key": "technical_fit",
        "name": "Technical Fit Specialist",
        "model": "claude-sonnet-4-6",
        "system": (
            "You are the Technical Fit Specialist. You decide whether our "
            "product actually does what the RFP asks for.\n\n"
            "Inputs:\n"
            "- The RFP text\n"
            "- product-overview.md (the canonical capability map)\n\n"
            "Output: a structured fit assessment:\n"
            "1. Requirements we meet fully\n"
            "2. Requirements we meet partially (and what's missing)\n"
            "3. Requirements we don't meet at all\n"
            "4. Overall fit score: high / medium / low\n"
            "5. The single most important risk to flag to the coordinator"
        ),
    },
    {
        "key": "competitive",
        "name": "Competitive Intel Analyst",
        "model": "claude-haiku-4-5-20251001",  # Cheaper for a quick analyst lookup
        "system": (
            "You are the Competitive Intel Analyst. You identify who else "
            "is likely competing for this RFP and how we should position.\n\n"
            "Inputs:\n"
            "- The RFP text\n"
            "- The competitive-intel skill (your battlecard library)\n\n"
            "Output:\n"
            "1. The 2-3 most likely competitors based on the RFP shape\n"
            "2. For each: their probable strengths and weaknesses on THIS deal\n"
            "3. Our two best positioning angles\n"
            "4. One trap to avoid"
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
            tools=[
                {"type": "agent_toolset_20260401"},
                *(CRM_TOOLS if spec["key"] == "pricing" else []),
            ],
            metadata={
                "hackathon": "partner-basecamp-2026",
                "track": "specialist-swarm",
                "role": spec["key"],
            },
        )
        specialist_ids[spec["key"]] = agent.id
        print(f"  Created {spec['name']:32s} -> {agent.id}")

    Path(".specialist_ids.json").write_text(json.dumps(specialist_ids, indent=2))
    print(f"\nSaved {len(specialist_ids)} specialist IDs to .specialist_ids.json")
    print("Next: python upload_skills.py")


if __name__ == "__main__":
    main()
