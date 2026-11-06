# RFP Agent Team

A bid lead agent orchestrates specialist agents (requirements, technical fit, pricing, legal, competitive intel, reviewer). Each specialist can send out up to three helper agents. Together they turn an RFP into a proposal (Markdown + Word). Built directly on the Claude Messages API: the orchestration, its limits and the event stream live in our own Python code (`backend/rfp_orchestrator`). Details: [`backend/ORCHESTRATION.md`](./backend/ORCHESTRATION.md).

Live at https://basecamp.pgoell.com (shared password; ask Pascal).

## Layout

```
backend/    Python, FastAPI.
  rfp_orchestrator/  the agent team: roster + prompts (agents.py), limits (config.py), runtime
  app/main.py        the API under /api: start runs, stream their events (SSE), download files
  tests/             offline tests with a scripted fake client (no API calls)
  skills/            one skill per specialist, injected into its system prompt
  synthetic-data/    the sample RFP and the reference files the agents read
frontend/   Bun and React. server.ts serves the page and, in development, forwards /api.
docs/       scenario cards and stretch goals
```

## Run it locally

You need [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh).

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env     # gitignored; repo root or backend/

cd backend
uv sync
uv run fastapi dev app/main.py        # http://localhost:8000
uv run python -m rfp_orchestrator     # or: one run in the terminal, no frontend
uv run python -m pytest tests -q      # offline tests

cd frontend                            # in a second terminal
bun install
bun dev                                # http://localhost:3000
```

## Change the agents

Edit `backend/rfp_orchestrator/agents.py` (prompts, models, roster) or `config.py` (limits). No setup step: the next run uses the change. Limits can also be set by env var, e.g. `RFP_MAX_CHILDREN_SPECIALIST=3`, `RFP_MAX_TOTAL_AGENTS=40`, `RFP_MAX_PARALLEL_RUNS=2` (see ORCHESTRATION.md).

## Deploy

Every push to `main` deploys. The **deploy** workflow runs on a runner on the server: it builds both images, pushes them to GHCR and restarts the containers. The compose file, the env file and the Caddy route live in the server-infra repo.

Pull requests run **check** on GitHub's own runners: the backend imports, the offline tests pass and the frontend builds. The server needs `ANTHROPIC_API_KEY` in its env file. Run workspaces live in `/app/outputs` inside the container and are lost on redeploy.

## Pick a scenario card

Three cards in [`docs/scenario-cards.md`](./docs/scenario-cards.md). Each gives you a coordinator and a different roster of specialists. Different teams should pick different cards.

## Stretch goals

See [`docs/stretch-goals.md`](./docs/stretch-goals.md):

- **Custom firm-voice skill**: codify your own firm's voice
- **Critic sub-agent**: a fifth agent that reviews the coordinator's draft before it ships
- **Memory across deals**: the coordinator remembers past wins and reuses the right ones
- **Synthetic MCP for past wins**: wire a fake CRM to the pricing specialist

## Demo

Start a run in the web app and narrate the agent tree: the bid lead fans out to the specialists in parallel, they may send out helpers, the reviewer pushes back, and the Word document shows up under Deliverables at the end.
