# Stagehands

**A director, four stagehands, and a stage that tells them when they've got it wrong.**

*Partner Basecamp — Option 3, Specialist Swarm*

**Concept landed:** Skills, plugins & sub-agents
**Tech:** [Claude Managed Agents multi-agent](https://platform.claude.com/docs/en/managed-agents/multi-agent) + [custom Skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) + a local Godot 4.7 engine as the verification gate
**Time:** 60 minutes
**Output:** A playable Godot 2D platformer scene, built by a coordinator and four specialists, and **proven to load by a real engine** before anyone claims it works.

## The pitch

This is the architecture that wins the next $50M transformation deal:
**coordinator + specialists + skills**. A senior lead orchestrates; specialists
own their lanes; the lead integrates.

The name is not decoration. Godot is named after *Waiting for Godot*; a
**scene** is both the engine's core abstraction and a thing a theatre crew
builds; and the coordinator here is a **Technical Director**, which is a real
role — the person who runs the technical crew. Stagehands own one craft each,
work in parallel, stay invisible, and are judged only on whether the thing
holds up when the lights come on.

The reason this version of it is worth watching is the last step. Most agent
demos end with a document, and a document can only be reviewed — you cannot
tell from looking whether it is right. A Godot scene either loads in a real
engine or it does not. So this swarm ships its work to a locally installed
Godot 4.7, gets back compiler-grade errors with file and line numbers, and
**repairs itself from them**.

That closed loop — delegate, build, verify against ground truth, repair — is
the part clients should copy.

## Architecture

```
run_scene_build.py  (local orchestrator)
        │  level brief
        ▼
  ┌─────────────────────────────────────────────┐
  │ Technical Director (coordinator, cloud)     │
  │   ├─ Level Designer      level.tscn         │
  │   ├─ Player Controller   player.tscn/.gd    │  threads run in parallel,
  │   ├─ Game Feel           pickups, camera    │  sharing one container
  │   ├─ Scene Integrator    main.tscn          │
  │   └─ Build Validator     triages errors     │
  └─────────────────────────────────────────────┘
        │  agents write to /mnt/session/outputs/
        ▼
  download → godot_project/
        ▼
  godot_verify.py   ← LOCAL Godot 4.7.2, headless
     stage 1  --import ×2            .tscn load + .gd parse errors
     stage 2  --script _validate.gd  load + instantiate every scene
     stage 3  --quit-after 120       boot the main scene, runtime errors
        │
        ├── clean ──► ✅ open it in Godot and play it
        └── errors ─► findings sent back into the SAME session →
                      Build Validator triages → specialists patch →
                      re-download → re-verify   (up to --max-rounds)
```

## Setup (5 min)

You need a workspace API key on the Console (multi-agent is in research
preview — your workspace may need to be granted access), and Godot 4.7+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then put your key in it
```

`.env` holds `ANTHROPIC_API_KEY` and `GODOT_BIN`. `GODOT_BIN` is optional if
Godot is at `/Applications/Godot.app` or on your `PATH`.

## Core build (25 min)

```bash
.venv/bin/python setup_environment.py     # cloud container for the session
.venv/bin/python create_specialists.py    # the five specialists
.venv/bin/python upload_skills.py         # skills → matching specialist
.venv/bin/python create_coordinator.py    # the Technical Director
.venv/bin/python run_scene_build.py       # build + verify + repair
```

The last one is the demo. It streams the event fan-out, downloads what the
swarm wrote, runs Godot against it, and loops.

When it passes:

```bash
"$GODOT_BIN" --path godot_project        # opens the project — press F5 to play
```

### Resuming instead of rebuilding

A session keeps its container and every thread's context, so you never have to
pay for the build round twice:

```bash
.venv/bin/python run_scene_build.py --resume-session last --budget-usd 15
```

This skips round 0, re-downloads whatever the session already produced, and
goes straight to verify → repair. It also raises the session's spend cap on
the way in — useful because a budget can be **changed** but never *added* to a
session created without one, and never re-added once removed.

## Measured on a real run

First end-to-end run, `claude-opus-5` for all six agents:

| | |
| --- | --- |
| Wall clock, build round | ~10 min (three builders genuinely parallel) |
| Cost, build round | **$2.23** |
| Verification | **passed first time — zero repair rounds** |
| Output | 6 files, 583 lines, 36 nodes, 3 collectibles per the brief |

Per-agent cost that run: coordinator $0.82, Level Designer $0.46, Player
Controller $0.43, Game Feel $0.37, Scene Integrator $0.14. Budget for ~$3–6
per scene with a repair round or two.

## Why the harness looks the way it does

`godot_verify.py` was calibrated empirically: a known-good scene was broken
four ways and the logs diffed. The result justifies every design choice.

| Fault injected | import | validate | boot | caught by |
| --- | --- | --- | --- | --- |
| GDScript syntax error | 0 | **1** | 0 | validator + log |
| `ext_resource` bad path | 0 | 0 | 0 | **log only** (stage 1) |
| missing `sub_resource` | 0 | **1** | 0 | validator + log |
| runtime null deref | 0 | 0 | 0 | **log only** (stage 3) |

**Godot's own exit code was `0` for all four.** So the harness never trusts
exit codes — it scrapes the merged output — and all three stages are required,
because no single stage catches everything.

Other things learned the hard way, all handled:

- A GDScript parse error **does not raise**. The node silently loads with no
  script. Only `Script.can_instantiate()` reveals it.
- Godot colours its output with ANSI escapes even when redirected.
- `--import` must run twice: on a cold tree `class_name` registration has not
  happened, producing phantom "Could not find base class" errors.
- An unrecognised flag makes Godot **hang forever**, and macOS has no
  `timeout(1)` — every invocation is bounded by a Python subprocess timeout.
- `load_steps` is deprecated as of Godot 4.6 and `uid://` should be omitted
  entirely. A model working from older training data gets both wrong, so the
  `godot-scene-format` skill states them explicitly.
- **Attach the format skill to everyone who writes the format.** On the first
  run it was on the Scene Integrator alone: `main.tscn` came back correct
  while `level`, `player` and `pickup` all emitted the deprecated
  `load_steps=N`. Four agents write `.tscn`, so four agents need the rules —
  `upload_skills.py` now maps one skill to many specialists.
- The Managed Agents SSE stream needs two guards, and the starter code had
  neither. Sending the kickoff *inside* `with ...stream()` deadlocks, because
  the stream blocks in `__enter__` until an event arrives and none can until
  you send. And SSE has no replay, so a mid-turn drop leaves the client
  waiting on a session that already finished. `stream_turn` sends from a
  thread and runs a rolling watchdog that reconciles against session status
  whenever the stream goes quiet.

## What's in this folder

```
├── setup_environment.py            cloud environment
├── create_specialists.py           the five specialists
├── create_coordinator.py           the Technical Director
├── upload_skills.py                Skills API upload + attach
├── run_scene_build.py              orchestrator + repair loop  ← the demo
├── godot_verify.py                 the local engine gate       ← the payoff
├── download_deliverable.py         re-fetch from an older session
├── stretch_playtest_subagent.py    stretch: the Playtest Critic
├── skills/
│   ├── godot-scene-format/         .tscn format  → Scene Integrator
│   ├── godot-level-layout/         geometry      → Level Designer
│   ├── gdscript-character-body-2d/ movement      → Player Controller
│   ├── godot-game-feel/            camera/pickups→ Game Feel
│   └── godot-error-triage/         error → owner → Build Validator
├── synthetic-data/
│   └── level-brief-crystal-caverns.md      the trigger
├── godot_project/
│   ├── project.godot               HARNESS-OWNED: main scene, InputMap
│   └── _validate.gd                HARNESS-OWNED: stage-2 validator
└── reference-scene/                known-good scene; the skill's worked example
```

`godot_project/` starts with only the two harness-owned files, so a run that
produces nothing cannot be mistaken for a run that succeeded.

## Two-minute demo

Two monitors:

- **Monitor 1:** `run_scene_build.py` streaming. Five `[thread spawned]` lines
  within seconds of each other, replies flowing back, then the verify block
  printing real Godot errors with `res://player.gd:32` line numbers, then a
  repair round fixing exactly those.
- **Monitor 2:** Godot open on `godot_project`. Press F5 and play the level
  the swarm just wrote.

Narrate the verify block. "The engine said no, and the swarm fixed it" is the
line that lands.

## Stretch goals

See [`stretch-goals.md`](./stretch-goals.md). The big one is S1 — the Playtest
Critic, which judges whether the level is *fun*, a question the engine cannot
answer.
