# San Francisco Route Specialist Swarm

A coordinator-and-specialists routing demo built with Anthropic Managed
Agents. A user supplies an origin, destination, and route style; the dispatcher
selects exactly one of five specialists to propose a path for a 5:00 PM trip in
the San Francisco / SFO area.

The route styles are:

- `fitness_coach` — a safe walking, running, or cycling workout;
- `scenic_route` — views, parks, architecture, and landmarks;
- `traffic_avoider` — a reliable commute that avoids congestion;
- `cost_effective` — the lowest practical total trip cost;
- `bar_crawl` — a responsible adult crawl using walking or hired transport.

## Requirements

- Python 3.10+
- An Anthropic API key with access to Managed Agents

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-api-key"
```

## Build and run

1. **Provision an environment.** Run `python setup_environment.py`. The
   environment ID is saved to `.environment_id` and reused on later runs.
2. **Create specialists.** Run `python create_specialists.py`. IDs are saved to
   `.specialist_ids.json`.
3. **Create the coordinator.** Run `python create_coordinator.py`. Its ID is
   saved to `.coordinator_id`.
4. **Add optional skills.** Create skill directories under `skills/`, each
   containing a `SKILL.md` with YAML frontmatter (`name` and `description`).
   Map each directory to a specialist key in `SKILL_TO_SPECIALIST` in
   [`upload_skills.py`](./upload_skills.py), then run `python upload_skills.py`.
5. **Request a route.** Choose a specialist and provide both endpoints:

   ```bash
   python run_swarm.py \
     "Ferry Building" \
     "Golden Gate Park" \
     --specialist scenic_route \
     --constraints "Avoid steep hills"
   ```

   Add `--context path/to/context.txt` when extra route context is useful. The
   event stream is printed and the coordinator transcript is saved under
   `outputs/`.
6. **Download session files later if needed.** Run
   `python download_deliverable.py [session_id]`. If no ID is provided, it
   uses `.last_session_id`.

## Routing behavior

- The selected specialist is the only one consulted for a request.
- The departure time is fixed at 5:00 PM Pacific time.
- Routes include ordered legs, estimates, rationale, and checks to make before
  departure.
- Specialists must label estimates and may not fabricate live traffic,
  closures, transit arrivals, prices, weather, or venue hours.
- These are route suggestions, not turn-by-turn navigation.

## Project files

```text
.
├── README.md
├── requirements.txt
├── create_specialists.py       # Creates specialist agents
├── create_coordinator.py       # Creates the coordinator agent
├── setup_environment.py        # Provisions a Managed Agents environment
├── upload_skills.py            # Uploads and attaches custom skills
├── run_swarm.py                # Runs a task and streams session events
├── download_deliverable.py     # Downloads files from a session
└── skills/                     # Add custom skill directories here
```

See the [Managed Agents documentation](https://platform.claude.com/docs/en/managed-agents/multi-agent)
and [Agent Skills documentation](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
for API details.
