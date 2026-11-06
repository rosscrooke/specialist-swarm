"""
Stretch: add a Critic sub-agent to the coordinator's roster.

The critic's job is to review the coordinator's draft before it goes out.
It must produce one of three verdicts:
- "ship it" (with a brief why)
- "revise" (with specific revisions)
- "stop" (with reason — e.g., we shouldn't pursue this deal)

This script creates the critic agent and updates the coordinator's roster
to include it. Then update the coordinator's system prompt to "always
consult the Critic on the draft before finalising."

Usage:
    python stretch_critic_subagent.py
"""

import json
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


CRITIC_SYSTEM = """\
You are the Deal Desk Critic. You don't write proposals. You review them.

When the coordinator asks for your review, you'll receive:
- The draft proposal
- The RFP (for context)

Your job: deliver one of three verdicts.

1. **SHIP IT** — the proposal is solid, with at most cosmetic suggestions.
2. **REVISE** — specific issues that need fixing. List them tersely. No more
   than 5 issues; if there are more, the proposal isn't ready.
3. **STOP** — we shouldn't pursue this deal. Reasons might include: terms
   we can't deliver, mismatched scale, regulatory issues, strategic conflict.

Be sceptical. Your value to the coordinator is that you push back. A senior
partner who never gets pushback gets sloppy.

Lead your reply with: VERDICT: SHIP IT / REVISE / STOP.
"""


def main() -> None:
    load_dotenv()  # reads ANTHROPIC_API_KEY from .env when it isn't exported
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    coordinator_id = Path(".coordinator_id").read_text().strip()
    specialist_ids = json.loads(Path(".specialist_ids.json").read_text())

    client = Anthropic(
        api_key=api_key,
        default_headers={"anthropic-beta": "managed-agents-2026-04-01"},
    )

    # Create the critic
    critic = client.beta.agents.create(
        name="Deal Desk Critic",
        model="claude-opus-4-7",  # The critic needs to be sharp
        system=CRITIC_SYSTEM,
        tools=[{"type": "agent_toolset_20260401"}],
        metadata={
            "hackathon": "partner-basecamp-2026",
            "track": "specialist-swarm",
            "role": "critic",
        },
    )
    print(f"Critic created: {critic.id}")

    # Add critic to specialist IDs and persist
    specialist_ids["critic"] = critic.id
    Path(".specialist_ids.json").write_text(json.dumps(specialist_ids, indent=2))

    # Update coordinator's roster to include the critic
    coordinator = client.beta.agents.retrieve(coordinator_id)
    new_roster = list(coordinator.multiagent.agents) + [
        {"type": "agent", "id": critic.id}
    ]

    # Append critic guidance to the coordinator's system prompt
    new_system = coordinator.system + (
        "\n\n# Critic\n\n"
        "Before producing the final document, send your draft to the Deal "
        "Desk Critic. The Critic will reply with one of: SHIP IT, REVISE, "
        "or STOP.\n"
        "- If SHIP IT: produce the final docx.\n"
        "- If REVISE: address the issues and re-submit to the Critic. "
        "Repeat at most twice.\n"
        "- If STOP: report to the user with the Critic's reasoning. Do "
        "NOT produce the final docx.\n"
    )

    client.beta.agents.update(
        coordinator_id,
        version=coordinator.version,
        system=new_system,
        multiagent={"type": "coordinator", "agents": new_roster},
    )

    print(f"Coordinator roster updated. Now includes critic.")
    print("Re-run run_deal_desk.py to see the critic in action.")


if __name__ == "__main__":
    main()
