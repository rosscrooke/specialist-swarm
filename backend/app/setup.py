"""Create or update the environment, skills and agents, and save their ids.

    uv run python -m app.setup

Reads the ids in swarm.json and updates those agents in place, so running it
again after you change app/agents.py keeps the same ids. Commit swarm.json:
the ids are not secret, and the deployed backend reads them from it.
"""

import json
from pathlib import Path

from anthropic import Anthropic
from anthropic.lib import files_from_dir

from app.agents import COORDINATOR, METADATA, SPECIALISTS, TOOLS

ROOT = Path(__file__).resolve().parent.parent
SWARM = ROOT / "swarm.json"


def upsert_agent(client: Anthropic, agent_id: str | None, **config) -> str:
    if agent_id:
        current = client.beta.agents.retrieve(agent_id)
        client.beta.agents.update(agent_id, version=current.version, **config)
        print(f"  updated {config['name']:28s} {agent_id}")
        return agent_id
    agent = client.beta.agents.create(**config)
    print(f"  created {config['name']:28s} {agent.id}")
    return agent.id


def main() -> None:
    client = Anthropic()
    swarm = json.loads(SWARM.read_text()) if SWARM.exists() else {}
    swarm.setdefault("specialists", {})
    swarm.setdefault("skills", {})

    try:
        build(client, swarm)
    finally:
        # Also after a failure, so a second run reuses what the first made.
        SWARM.write_text(json.dumps(swarm, indent=2) + "\n")
    print(f"Saved ids to {SWARM.name}. Commit it.")


def build(client: Anthropic, swarm: dict) -> None:
    if "environment_id" not in swarm:
        env = client.beta.environments.create(
            name="specialist-swarm-env",
            config={"type": "cloud", "networking": {"type": "unrestricted"}},
        )
        swarm["environment_id"] = env.id
        print(f"  created environment {env.id}")

    # Skills keep their ids in swarm.json. The org shares one Skills API rate
    # limit and many skills, so look nothing up; titles must be unique in the
    # org, hence the prefix.
    for spec in SPECIALISTS:
        name = spec["skill"]
        if name and name not in swarm["skills"]:
            skill = client.skills.create(
                display_name=f"Deal Desk {name}", files=files_from_dir(str(ROOT / "skills" / name))
            )
            swarm["skills"][name] = skill.id
            print(f"  uploaded skill {name} {skill.id}")

    for spec in SPECIALISTS:
        skills = (
            [{"type": "custom", "skill_id": swarm["skills"][spec["skill"]], "version": "latest"}]
            if spec["skill"]
            else []
        )
        swarm["specialists"][spec["key"]] = upsert_agent(
            client,
            swarm["specialists"].get(spec["key"]),
            name=spec["name"],
            model=spec["model"],
            system=spec["system"],
            tools=TOOLS,
            skills=skills,
            metadata={**METADATA, "role": spec["key"]},
        )

    swarm["coordinator_id"] = upsert_agent(
        client,
        swarm.get("coordinator_id"),
        name=COORDINATOR["name"],
        model=COORDINATOR["model"],
        system=COORDINATOR["system"],
        tools=TOOLS,
        multiagent={
            "type": "coordinator",
            "agents": [{"type": "agent", "id": i} for i in swarm["specialists"].values()],
        },
        metadata={**METADATA, "role": "coordinator"},
    )


if __name__ == "__main__":
    main()
