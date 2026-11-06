# Deal Desk: specialist swarm

A coordinator agent hands an RFP to four specialist agents (pricing, legal, technical fit, competitive intel), each with its own skill, and turns their answers into a Word document. Built on [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/multi-agent).

Live at https://basecamp.pgoell.com (shared password; ask Pascal).

## Layout

```
backend/    Python, FastAPI. Starts sessions and streams their events.
  app/agents.py      the agents: prompts, models, skills. Edit here.
  app/setup.py       creates or updates the agents, writes swarm.json
  app/main.py        the API under /api
  swarm.json         agent and environment ids (not secret, committed)
  skills/            one custom skill per specialist
  synthetic-data/    the sample RFP and the files the specialists read
frontend/   Bun and React. server.ts serves the page and, in development, forwards /api.
docs/       scenario cards and stretch goals
```

## Run it locally

You need [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh).

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > backend/.env    # gitignored

cd backend
uv sync
set -a; . ./.env; set +a
uv run fastapi dev app/main.py        # http://localhost:8000

cd frontend                            # in a second terminal
bun install
bun dev                                # http://localhost:3000
```

The backend uses the agents in `backend/swarm.json`, which the whole team shares.

## Change the agents

Edit `backend/app/agents.py`, then either:

- run `uv run python -m app.setup` in `backend/` and commit `swarm.json` if it changed, or
- start the **setup-agents** workflow on GitHub (Actions tab). It runs the same script with the team's key, commits `swarm.json` and deploys.

Setup updates the agents in place, so their ids stay the same. Delete an entry from `swarm.json` to get a fresh one.

## Deploy

Every push to `main` deploys. The **deploy** workflow runs on a runner on the server: it builds both images, pushes them to GHCR and restarts the containers. The compose file, the env file and the Caddy route live in the server-infra repo.

Pull requests run **check** on GitHub's own runners: the backend imports and the frontend builds.

## Pick a scenario card

Three cards in [`docs/scenario-cards.md`](./docs/scenario-cards.md). Each gives you a coordinator and a different roster of specialists. Different teams should pick different cards.

## Stretch goals

See [`docs/stretch-goals.md`](./docs/stretch-goals.md):

- **Custom firm-voice skill**: codify your own firm's voice
- **Critic sub-agent**: a fifth agent that reviews the coordinator's draft before it ships
- **Memory across deals**: the coordinator remembers past wins and reuses the right ones
- **Synthetic MCP for past wins**: wire a fake CRM to the pricing specialist

## Demo

Start a run in the web app and narrate the event log: threads spawn, specialists work side by side, replies come back. The Word document shows up under Deliverables when the swarm finishes.
