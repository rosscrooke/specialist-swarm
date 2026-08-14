# Text-Based Health Coaching Swarm — Implementation Plan

## Context

We're reusing the `specialist-swarm` demo's architecture (coordinator + specialists + skills on the
Claude Managed Agents multi-agent API) to build **our own version**: a **personal health-coaching
agent that runs over texting**. Someone texts it their week (or it pulls from synthetic
Apple Health / Garmin / Whoop / MyFitnessPal / Oura exports), and it texts back concrete, encouraging
changes to make next week across **three domains — nutrition, workouts, recovery — all pointed at one
stated goal** (e.g. "run a marathon," "do a handstand," "crush the Salkantay trail").

This replaces the earlier docx-oriented draft (`health-plan-swarm/DESIGN.md` — now partially
superseded; update it during implementation). The source of truth is the team's Notion brainstorm
(pasted by the user; the page itself is behind Fractional auth and not directly fetchable).

Decisions locked with the user:
- **Runtime:** same Managed Agents API (`beta.agents` / coordinator / `beta.sessions`).
- **Interface:** *texting.* Simulated as a **text-message-style chat loop in the terminal** — you
  "text" your week, the coach "texts" back. (Real SMS via Twilio → stretch goal.)
- **Onboarding:** an **interactive onboarding chat** gathers goal + constraints once and saves a
  profile the weekly run reads.
- **Persona (synthetic):** a very average San Francisco resident — a typical 30-something with a
  desk job, moderate/inconsistent activity, average sleep, and no special dietary restrictions.
- **Model tiering:** start cheap — Haiku → Sonnet → Opus, escalate only where needed.
- **Restraint is a feature:** not every agent must recommend a change each week; acknowledging that
  the user is already on track is valid output.

Kickoff prompt (per brainstorm): *"Based on the past week of workouts, nutrition, and recovery,
please recommend changes to make next week to each to meet my stated goal."*

## Approach

New project at `/Users/leelasarukkai/Basecamp-Exercises/health-coach-swarm/`, adapting the original
scripts. Two entry points instead of one:

1. **Onboarding** (`onboard.py`) — interactive chat → `profile.json` (run once per user).
2. **Weekly check-in** (`run_weekly_checkin.py`) — the texting loop: loads profile + synthetic weekly
   data, the coordinator fans out to the domain agents in parallel, Safety screens, Synthesis formats
   the reply, and it "texts back." Multi-turn so the user can reply and iterate.

Setup pipeline (unchanged order, adapted content):
`setup_environment.py` → `create_specialists.py` → `upload_skills.py` → `create_coordinator.py`
→ then `onboard.py` (once) → `run_weekly_checkin.py`.

### Roster (coordinator + 6 agents)

| Agent | Model | Role | Skill / rules |
| --- | --- | --- | --- |
| **Coordinator** | `opus` | Orchestrates the weekly run; reconciles the domain outputs into one coherent set of changes | `multiagent: coordinator` |
| **Nutrition agent** | `sonnet` | Weekly meals + a **shared shopping list that reuses ingredients across meals**; pescatarian-aware; acts as a nutritionist, not a dietician | skill `nutrition-guidelines` |
| **Workout agent** | `sonnet` | Next-week workout changes toward the goal; injury/history/equipment aware | skill `training-periodization` |
| **Recovery agent** | `haiku` | Sleep + subjective-wellness read; rest/readiness guidance | skill `recovery-protocol` |
| **Safety Screener** | `sonnet` | Screens the combined recommendation for danger (injury, pregnancy, weather e.g. "don't run in a blizzard", overreaching); tags **stop / caution / ok**; owns the not-medical-advice disclaimer | prompt rules |
| **Synthesis agent** | `sonnet` | Formats the reconciled substance into one warm, concrete, texting-voice message in the preferred structure | prompt rules |
| **Onboarding agent** | `sonnet` | Interactive Q&A to capture goal + constraints once; emits a structured `profile.json` | prompt rules (own flow) |

Coordinator's callable roster = Nutrition, Workout, Recovery, Safety, Synthesis (5). The Onboarding
agent runs in its own session (`onboard.py`), not called by the weekly coordinator.

## Files to create

All under `/Users/leelasarukkai/Basecamp-Exercises/health-coach-swarm/`, adapting from the original
`/Users/leelasarukkai/Basecamp-Exercises/specialist-swarm/`.

### Pipeline / entry scripts
- **`setup_environment.py`** — copy verbatim; rename env `health-coach-swarm-env`. Reuse the
  idempotent `.environment_id` guard.
- **`create_specialists.py`** — replace `SPECIALISTS` with the 6 agents above (narrow prompts). Keep
  the create loop, `agent_toolset_20260401` tools, `.specialist_ids.json` write, and the
  `managed-agents-2026-04-01` beta header exactly (`create_specialists.py:107-124`).
- **`upload_skills.py`** — set `SKILL_TO_SPECIALIST = {"nutrition-guidelines": "nutrition",
  "training-periodization": "workout", "recovery-protocol": "recovery"}`. Reuse the idempotent
  upload/reuse-by-title + attach logic verbatim (`upload_skills.py:40-94`).
- **`create_coordinator.py`** — replace `COORDINATOR_SYSTEM` with the coach-coordinator prompt; roster
  = the 5 (exclude onboarding). Keep the `multiagent={"type":"coordinator","agents":[...]}` wiring
  (`create_coordinator.py:89-106`).
- **`onboard.py`** *(new)* — opens a session against the Onboarding agent; interactive terminal Q&A
  (goal, preferred workout types, dietary restrictions/prefs + meals-per-day, sleep baseline,
  work/time constraints, injury/health history + pregnancy, equipment, subjective baseline); instructs
  the agent to end with a fenced JSON block; parse it and write `profile.json`.
- **`run_weekly_checkin.py`** *(renamed from `run_deal_desk.py`)* — the texting loop. First turn
  bundles `profile.json` + the synthetic weekly data (§ data) + the kickoff prompt as the user's
  "text"; reuse the event-stream loop (`run_deal_desk.py:78-113`) to show the parallel fan-out; print
  the coordinator's reply as a "text back"; then loop reading further user "texts" via
  `beta.sessions.events.send` until exit. Output is text — drop the docx/file-download step (or keep
  as a no-op safety net).

### Skills (`skills/*/SKILL.md`, YAML frontmatter: `name` + trigger-rich `description`)
- **`skills/nutrition-guidelines/SKILL.md`** — macro/TDEE method, protein targets, meal-timing, and a
  **shared-ingredient shopping strategy** (minimize unique ingredients across the week), dietary-restriction
  handling, hard "don't recommend" list.
- **`skills/training-periodization/SKILL.md`** — goal-based progression templates (marathon /
  handstand / couch-to-5K / multi-day trek), progressive overload + deload, injury/equipment
  adaptations.
- **`skills/recovery-protocol/SKILL.md`** — sleep standards, HRV/readiness bands, rest-day rules,
  over-reaching warning signs, how subjective wellness modulates load.

### Synthetic data + schema (`synthetic-data/`, `schema/`)
Model the integration story with per-source exports that normalize into one schema:
- `synthetic-data/garmin-workouts.json` — a week of workouts w/ HR, GPS, elevation (a typical mix:
  commute walks, a couple gym sessions, an occasional run or weekend hike).
- `synthetic-data/whoop-recovery.json` — sleep, HRV, recovery score (Whoop/Oura style).
- `synthetic-data/myfitnesspal-nutrition.json` — daily macros + meals (typical omnivore intake; no
  restrictions).
- `synthetic-data/checkins.json` — post-workout "how did that feel?" + subjective wellness (mood/stress).
- `schema/ingestion-schema.md` — the normalized weekly schema and how each source maps into it.
- `profile.json` — produced by `onboard.py` (a sample committed for a fast demo path).

### Docs
- `README.md` — rewritten for the texting health-coach flow.
- `scenario-cards.md` — goal variants (marathon, handstand, couch-to-5K, Salkantay trek).
- `stretch-goals.md` — real SMS (Twilio), weather-aware safety (live env), more integrations,
  cross-week memory, an **evals harness**, and the in-progress **"active edits"** revision loop.
- `requirements.txt` — copy verbatim (`anthropic>=0.40.0`, `python-dotenv>=1.0.0`).

## Reused code (do not reinvent)
From `/Users/leelasarukkai/Basecamp-Exercises/specialist-swarm/`:
- `managed-agents-2026-04-01` beta header + `agent_toolset_20260401` pattern (`create_specialists.py`).
- Idempotent skill upload/attach (`upload_skills.py:40-94`) — verbatim.
- Coordinator `multiagent` wiring (`create_coordinator.py:89-106`).
- Event-stream loop (`run_deal_desk.py:78-113`) — reused; `beta.sessions.events.send` also drives the
  multi-turn texting loop.
- `setup_environment.py`, `requirements.txt` — as-is.

## Verification

From the new project dir with `ANTHROPIC_API_KEY` set (workspace key with managed-agents
research-preview access):

```bash
cd /Users/leelasarukkai/Basecamp-Exercises/health-coach-swarm
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
python setup_environment.py       # .environment_id
python create_specialists.py      # .specialist_ids.json (6 agents)
python upload_skills.py           # 3 skills uploaded + attached (idempotent)
python create_coordinator.py      # .coordinator_id (rosters 5)
python onboard.py                 # interactive → profile.json
python run_weekly_checkin.py      # texting loop → coach "texts back"
```

Success criteria:
1. `onboard.py` produces a `profile.json` capturing the goal + all constraints.
2. `create_specialists.py` prints 6 IDs; coordinator's roster is 5 (onboarding excluded).
3. `run_weekly_checkin.py` event stream shows parallel `[thread spawned]`/`[thread running]`/
   `[reply ←]` for Nutrition + Workout + Recovery, then Safety, then Synthesis — the parallelism is
   the demo.
4. The final "text back" is a single coherent, encouraging message covering all three domains pointed
   at the goal; respects dietary + injury + equipment + schedule constraints; the nutrition part
   reuses ingredients across meals; a not-medical-advice line is present.
5. Restraint works: seeding an already-on-track week yields "keep doing X" rather than forced changes.
6. Multi-turn works: replying in the loop (e.g. "I only have 3 days next week") produces a revised
   reply in the same session.
7. Safety works (spot-check / eval): injecting a dangerous signal (e.g. sharp knee pain + "add
   sprints", or a blizzard + outdoor run) makes the Safety Screener flag it and the reply adapts.

No automated tests exist in the original (it's a demo); verification is running the two flows and
inspecting the streamed events + the texted replies. A lightweight **evals** harness (criteria 4–7 as
scripted checks) is a documented stretch. If live API/preview access isn't available, we stop at a dry
review (scripts import + construct requests correctly) and run the full flow once access is confirmed.

## Out of scope / follow-ups
- **Real SMS (Twilio)**, weather/live-environment safety, additional device integrations — stretch.
- **Cross-week memory** (coach remembers last week) and the **"active edits"** interactive revision
  loop (in-progress in Notion) — stretch.
- Update/retire the docx-oriented `health-plan-swarm/DESIGN.md` to match this plan during
  implementation.
```
