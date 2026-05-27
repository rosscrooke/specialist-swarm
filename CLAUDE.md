# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Approval policy

Ask the user for explicit confirmation before any local file modification — creating, editing, overwriting, or deleting files in this repo (including the hidden `.environment_id` / `.specialist_ids.json` / `.coordinator_id` / `.skill_ids.json` / `.last_session_id` dotfiles, and anything under `outputs/` or `skills/`).

Git operations do **not** require per-action approval — proceed with `add`, `commit`, `checkout`, `push`, branch creation, PR creation, etc. without asking each time.

Read-only operations (reading files, listing directories, running the existing Python scripts that only call the Anthropic API) do not require this approval. When in doubt on file edits, ask first.

## What this repo is

A 60-minute hackathon track ("Option 3 — Specialist Swarm") that builds a coordinator + 4 specialist sub-agents using the **Claude Managed Agents multi-agent API** (currently in research preview — workspace access must be granted). The chosen scenario is the **Deal Desk**: ingest an RFP, fan out work to Pricing / Legal / Technical Fit / Competitive Intel specialists, and synthesise a branded Word document proposal response. This is the only scenario this repo supports — see `scenario-cards.md` for the roster and `synthetic-data/rfp-acme-corp.md` for the trigger input.

## Common commands

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."   # required by every script

# One-time provision (in order):
python setup_environment.py     # creates cloud Environment    -> .environment_id
python create_specialists.py    # creates 4 specialist agents  -> .specialist_ids.json
python upload_skills.py         # packages skills/, attaches each to matching specialist -> .skill_ids.json
python create_coordinator.py    # creates coordinator agent    -> .coordinator_id

# Run the swarm against the synthetic RFP:
python run_deal_desk.py         # streams events, saves output to outputs/  -> .last_session_id

# Re-download deliverables from a past session:
python download_deliverable.py [session_id]   # defaults to .last_session_id

# Stretch: add the Critic sub-agent to the existing coordinator:
python stretch_critic_subagent.py
```

There are no tests, linter config, or build step. Iteration is "edit a script, re-run it."

## Architecture

### Two-stage object model (provisioning vs. execution)

Provisioning scripts (`create_*`, `upload_skills`, `setup_environment`) each create one type of Beta API object and persist the returned ID to a hidden dotfile in the repo root. Those dotfiles are the glue between scripts:

| File | Written by | Read by |
| --- | --- | --- |
| `.environment_id` | `setup_environment.py` | `run_deal_desk.py` |
| `.specialist_ids.json` | `create_specialists.py` | `upload_skills.py`, `create_coordinator.py`, `stretch_critic_subagent.py` |
| `.skill_ids.json` | `upload_skills.py` | (informational) |
| `.coordinator_id` | `create_coordinator.py` | `run_deal_desk.py`, `stretch_critic_subagent.py` |
| `.last_session_id` | `run_deal_desk.py` | `download_deliverable.py` |

To reset cleanly, delete these dotfiles (objects on the API side persist; the scripts simply won't re-find them). `upload_skills.py` and `setup_environment.py` are idempotent — they detect existing objects (by display title / dotfile presence) and reuse them.

### The multi-agent shape

- **Specialists** (`create_specialists.py`): four `beta.agents.create` calls, each with a narrow `system` prompt, `tools=[{"type": "agent_toolset_20260401"}]`, and a model (Sonnet for most, Haiku for the Competitive Intel "quick lookup"). No `multiagent` field — they're leaf agents.
- **Coordinator** (`create_coordinator.py`): one `beta.agents.create` with `model=claude-opus-4-7` (intentional — coordinator gets the strongest model) AND `multiagent={"type": "coordinator", "agents": [...]}` listing every specialist's ID. The coordinator's system prompt tells it to delegate to all four specialists in parallel and then synthesise.
- **Skills** (`upload_skills.py`): each skill in `skills/<name>/` is uploaded via `client.beta.skills.create(files=files_from_dir(...))` (uses `anthropic.lib.files_from_dir`), then attached to one specialist by updating that agent's `skills` array. The mapping is hardcoded in `SKILL_TO_SPECIALIST`. Skills are matched on display title for idempotent reuse — re-running the script won't create duplicates.
- **Session** (`run_deal_desk.py`): all execution happens inside `beta.sessions.create(agent=coordinator_id, environment_id=...)`. Events stream via `beta.sessions.events.stream(session_id)`; the user message is sent via `beta.sessions.events.send(...)`.

The visible-parallelism story is the demo: as the coordinator delegates, the event stream shows `session.thread_created` for each specialist, then `session.thread_status_running` in parallel, then `agent.thread_message_received` as replies fan back in. `run_deal_desk.py` prints a one-line marker for each of these so the cadence is human-narratable.

### Beta API header

All scripts that talk to multi-agent endpoints pass `anthropic-beta: managed-agents-2026-04-01`. Some pass it via `default_headers={...}` on the client; others pass it per-call via the `betas=[...]` kwarg (e.g. `beta.files.list(..., betas=["managed-agents-2026-04-01"])`). Both forms are in use — when adding new calls, match what the surrounding script does.

### Deliverables

Specialists run inside the cloud Environment's container; files they create (notably the branded `.docx`) live in the session's file scope, not on the local disk. `run_deal_desk.py` ends by listing `beta.files.list(scope_id=session.id)` and downloading each file to `outputs/`. `download_deliverable.py` is the standalone version of just that step — useful when the swarm produced a file but you killed the streaming script before the download.

### Skills are real content

`skills/pricing-playbook/SKILL.md`, `skills/legal-checklist/SKILL.md`, and `skills/competitive-intel/SKILL.md` contain actual decision tables (discount bands, red-line clauses, competitor battlecards). These are not boilerplate — the specialists cite them by name. The frontmatter `name` and `description` fields are how Claude decides when to invoke a skill, so changes there change behavior.

## Scenario notes

Stretch goals are in `stretch-goals.md`. `stretch_critic_subagent.py` is the only one with starter code; it mutates the existing coordinator (system prompt + roster) in place via `beta.agents.update` rather than re-creating it.
