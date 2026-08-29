"""
Stretch goal: add a Playtest Critic to the swarm.

The Build Validator answers "does it load?". The Playtest Critic answers the
harder question the engine cannot: "is it any good?" — jump spacing, pacing,
whether the level teaches what it later tests.

Unlike the rest of the setup scripts this one is idempotent: re-running it
finds the existing critic, updates it, and leaves the coordinator's roster
and system prompt alone rather than appending a second copy of both.

Usage:
    python stretch_playtest_subagent.py
"""

import json
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = os.environ.get("SWARM_MODEL", "claude-opus-5")
CRITIC_NAME = "Playtest Critic"

CRITIC_DESCRIPTION = (
    "Judges whether a level is actually fun and fair, not whether it loads. "
    "Give it the platform table, the controller tuning numbers and the brief; "
    "it returns a verdict and at most five concrete changes."
)

CRITIC_SYSTEM = """\
You are the Playtest Critic. You never write scene files. You are handed a
level's geometry and its controller tuning as numbers, and you say whether the
thing is worth playing.

You cannot see the level. Reason from the numbers — that is the job, and it is
how a designer reviews a layout in a spreadsheet before building it.

Check, in this order:

1. **Is every jump possible?** peak height = jump_velocity^2 / (2 * gravity);
   distance = speed * (2 * |jump_velocity| / gravity). Any required jump within
   10% of either limit is a defect, not a challenge — and a jump near BOTH
   limits at once is impossible regardless of what each number looks like alone.
2. **Does the level teach before it tests?** A mechanic used in a punishing
   spot must have appeared earlier somewhere safe.
3. **Is the pacing varied?** Three identical gaps in a row is one idea printed
   three times.
4. **Is the reward legible?** A collectible the player cannot see before
   committing to the jump is a trap, not a decision.
5. **Does it match the brief's stated feel?**

Lead your reply with exactly one of:

VERDICT: SHIP IT        — playable and worth the player's time
VERDICT: REVISE         — playable but weak; list the fixes
VERDICT: UNPLAYABLE     — a required jump is impossible; this must be fixed

On REVISE or UNPLAYABLE, give at most five changes, each as:

  CHANGE n — <what to change>
  Why: <the player experience problem, in one sentence>
  Owner: <Level Designer | Player Controller | Game Feel Specialist>

Be specific and numeric. "Move LedgeB down 24px" beats "make it easier".
Do not comment on file formats or engine errors — that is the Build
Validator's lane, not yours.
"""

ROSTER_NOTE = """

# Playtest Critic

Before you declare the build finished, send the Playtest Critic the Level
Designer's platform table, the Player Controller's tuning numbers, and the
original brief. If it returns UNPLAYABLE, dispatch its changes and re-verify —
a scene that loads but cannot be completed is not done. If it returns REVISE,
apply the changes that fit the remaining time and report the rest.
"""


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY (or put it in .env) before running.")

    ids_path = Path(".specialist_ids.json")
    coordinator_path = Path(".coordinator_id")
    if not ids_path.exists() or not coordinator_path.exists():
        raise SystemExit("Run create_specialists.py and create_coordinator.py first.")

    specialist_ids = json.loads(ids_path.read_text())
    coordinator_id = coordinator_path.read_text().strip()
    client = Anthropic()

    # --- create or update the critic -------------------------------------
    critic_id = specialist_ids.get("playtest_critic")
    if critic_id:
        current = client.beta.agents.retrieve(critic_id)
        client.beta.agents.update(
            critic_id,
            version=current.version,
            system=CRITIC_SYSTEM,
            description=CRITIC_DESCRIPTION,
        )
        print(f"Updated existing critic: {critic_id}")
    else:
        critic = client.beta.agents.create(
            name=CRITIC_NAME,
            description=CRITIC_DESCRIPTION,
            model=MODEL,
            system=CRITIC_SYSTEM,
            tools=[
                {
                    "type": "agent_toolset_20260401",
                    "default_config": {"enabled": False},
                    "configs": [{"name": n, "enabled": True} for n in ("read", "glob", "grep")],
                }
            ],
            metadata={
                "hackathon": "partner-basecamp-2026",
                "track": "godot-scene-swarm",
                "role": "playtest_critic",
            },
        )
        critic_id = critic.id
        specialist_ids["playtest_critic"] = critic_id
        ids_path.write_text(json.dumps(specialist_ids, indent=2))
        print(f"Created critic: {critic_id}")

    # --- attach to the coordinator, without duplicating -------------------
    coordinator = client.beta.agents.retrieve(coordinator_id)
    roster = list(coordinator.multiagent.agents) if coordinator.multiagent else []

    def entry_id(entry) -> str | None:
        if isinstance(entry, str):
            return entry
        return getattr(entry, "id", None) or (entry.get("id") if isinstance(entry, dict) else None)

    if any(entry_id(entry) == critic_id for entry in roster):
        print("Critic already on the roster — nothing to add.")
        return

    roster.append({"type": "agent", "id": critic_id})
    system = coordinator.system
    if "# Playtest Critic" not in system:
        system = system + ROSTER_NOTE

    client.beta.agents.update(
        coordinator_id,
        version=coordinator.version,
        system=system,
        multiagent={"type": "coordinator", "agents": roster},
    )
    print(f"Attached to coordinator {coordinator_id}. Roster is now {len(roster)} agents.")
    print("\nRe-run: python run_scene_build.py")


if __name__ == "__main__":
    main()
