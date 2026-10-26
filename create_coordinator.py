"""
Create the coordinator agent that orchestrates a specialist swarm.

The coordinator's roster comes from create_specialists.py. Customize its
instructions below to define how it should delegate and assemble the result.

Saves the coordinator's ID to .coordinator_id.

Usage:
    python create_coordinator.py
"""

import json
import os
from pathlib import Path

from anthropic import Anthropic


EXPECTED_SPECIALISTS = {
    "fitness_coach",
    "scenic_route",
    "traffic_avoider",
    "cost_effective",
    "bar_crawl",
}


COORDINATOR_SYSTEM = """\
You are the dispatcher for a San Francisco route-planning demo. Every request
contains an origin, a destination, a selected specialist, and a 5:00 PM local
departure time. Supported specialist keys are:

- fitness_coach: an active walking, running, or cycling route;
- scenic_route: a route emphasizing views, parks, and landmarks;
- traffic_avoider: a reliable route that avoids 5:00 PM congestion;
- cost_effective: the lowest practical door-to-door cost;
- bar_crawl: a responsible, walking/transit/rideshare crawl for adults.

Validate that the origin, destination, and specialist are present. Treat the
San Francisco / SFO area as the service area. If a location is ambiguous or
apparently unsupported, explain the issue and request only the missing detail.

For a valid request, delegate to exactly the selected specialist. Include the
origin, destination, fixed departure time, and all user constraints verbatim.
Do not ask other specialists for competing routes and do not silently replace
the selected objective. You may follow up with the selected specialist once if
its answer omits a required route element or violates a safety constraint.

Return the specialist's recommendation in this compact format:

Route style: <human-readable specialist name>
Summary: <one sentence>
Route:
1. <ordered leg>
2. <ordered leg>
Totals: <estimated duration, distance, and cost as applicable>
Why this fits: <brief explanation>
Before leaving: <live-data, safety, accessibility, or hours checks>

Preserve uncertainty labels. Never imply access to live traffic, transit,
closure, price, weather, or venue-hours data unless the specialist cites a
current source. This is route guidance, not turn-by-turn navigation.
"""


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    specialist_ids_path = Path(".specialist_ids.json")
    if not specialist_ids_path.exists():
        raise SystemExit("Run create_specialists.py first.")
    specialist_ids = json.loads(specialist_ids_path.read_text())
    configured_specialists = set(specialist_ids)
    if configured_specialists != EXPECTED_SPECIALISTS:
        missing = sorted(EXPECTED_SPECIALISTS - configured_specialists)
        unexpected = sorted(configured_specialists - EXPECTED_SPECIALISTS)
        raise SystemExit(
            "Specialist IDs do not match the route roster. Run "
            f"create_specialists.py again. Missing: {missing}; "
            f"unexpected: {unexpected}."
        )

    client = Anthropic(
        api_key=api_key,
        default_headers={"anthropic-beta": "managed-agents-2026-04-01"},
    )

    coordinator = client.beta.agents.create(
        name="San Francisco Route Dispatcher",
        model="claude-opus-4-7",
        system=COORDINATOR_SYSTEM,
        tools=[{"type": "agent_toolset_20260401"}],
        multiagent={
            "type": "coordinator",
            "agents": [
                {"type": "agent", "id": agent_id}
                for agent_id in specialist_ids.values()
            ],
        },
        metadata={"role": "route_dispatcher"},
    )

    Path(".coordinator_id").write_text(coordinator.id)
    print(f"Coordinator created: {coordinator.id}")
    print(f"Roster: {list(specialist_ids.keys())}")
    print("\nNext: python upload_skills.py (if using skills), then python run_swarm.py")


if __name__ == "__main__":
    main()
