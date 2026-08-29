# Stagehands, ported local

**Conversion spec** — moving the Godot scene swarm off Managed Agents and onto
Claude Code subagents, and keeping the only part that actually proves anything.

| | |
| --- | --- |
| Source | `specialist-swarm-godot` @ `stagehands-godot-swarm` |
| Engine | Godot 4.7.2 |
| Status | spec only, not built |

---

## 1. Why bother

The cloud architecture exists for exactly one reason: Managed Agents run in a
container with no Godot in it. Everything awkward about the current design
descends from that — writing to `/mnt/session/outputs/`, downloading files
back, ferrying engine errors into a repair round through a Python orchestrator.

Locally that constraint disappears and the repair loop collapses inward. Today
a malformed `.tscn` costs a full round trip: specialist writes → coordinator
integrates → download → verify → validator triages → back to the specialist.
Locally **each specialist runs the engine on its own file before it reports.**
Most of what the Build Validator does exists only because the builders are
currently blind.

Three of the hardest bugs in the cloud version also vanish outright: no SSE
stream means no deadlock and no watchdog, and no file bridge means no path
flattening.

---

## 2. The validation gate — port this first

This is the part that matters, and the part most likely to be quietly weakened
during a rewrite. The swarm is not what made the original work — **the verifier
is.** A document deliverable can only be reviewed; a Godot scene either loads in
a real engine or it doesn't. Remove the gate and you have five confident agents
and no way to tell whether any of them is right.

### 2.1 Godot's exit codes are worthless — measured, not assumed

The harness was calibrated by taking a known-good scene, breaking it four ways,
and diffing the logs. One fault per detection path:

| Injected fault | import | validate | boot | Detected by |
| --- | :---: | :---: | :---: | --- |
| GDScript syntax error | 0 | **1** | 0 | validator + log scrape |
| Bad `ext_resource` path | 0 | 0 | 0 | **log only — import** |
| Missing `sub_resource` | 0 | **1** | 0 | validator + log scrape |
| Runtime null dereference | 0 | 0 | 0 | **log only — boot** |

Godot's own exit code is `0` for all four. Two of the four are visible to
exactly *one* stage. Three non-negotiable rules follow:

- **Never trust an exit code.** Classify by scraping merged stdout+stderr. The
  only trustworthy exit code in the system is the one `_validate.gd` sets itself.
- **Keep all three stages.** Dropping one to "speed things up" is a silent
  regression that removes a whole fault class.
- **Bound every invocation with a timeout.** An unrecognised flag makes Godot
  hang forever, and macOS has no `timeout(1)`.

> **The subtle one.** A GDScript parse error **does not raise**. The script
> still loads as a `Resource`, still reports `is Script`, and the node simply
> ends up with no script attached — the scene loads and quietly does nothing.
> Only `Script.can_instantiate()` goes false. A validator that checks for `null`
> passes every broken script in the project.

### 2.2 Other engine behaviour the harness already absorbs

- Output is **ANSI-coloured even when redirected** — strip escapes before
  matching anything.
- `--import` must run **twice**. On a cold tree `class_name` registration hasn't
  happened, producing phantom "Could not find base class" errors that clear on
  the second pass.
- `--check-only` exits `0` on a script that cannot even be opened. Don't use it.
- `load_steps` is deprecated as of Godot 4.6, and `uid://` should be omitted
  entirely — a fabricated uid on an `ext_resource` is worse than none, because
  Godot prefers the uid over the path and then fails to resolve it.

### 2.3 Harness-owned files — keep these out of agent hands

Two files are the contract, not the deliverable. Whatever runtime sits on top,
no agent may write them:

- **`project.godot`** — pins the main scene, the viewport, and the InputMap
  (`move_left`, `move_right`, `jump`). Pinning input turned a coordination
  problem into a guarantee: zero input-related failures across the whole run.
  Generate the `[input]` block with `ProjectSettings.save()` rather than
  hand-writing the `Object(InputEventKey,…)` serialisation.
- **`_validate.gd`** — loads and instantiates every scene, compiles every
  script, and sets an exit code you control. It also emits
  `VALIDATE_FAIL|<path>|<reason>` lines so findings can be parsed without
  guessing at Godot's phrasing.

### 2.4 The regression test is not optional

`evals/harness_regression.py` re-injects all four faults and asserts each is
still caught. Free, offline, about three minutes. It guards the grader — and
**a broken grader is worse than no grader**, because every downstream check
turns green and reports success.

Run it after any change to the verifier, and treat a `FIXTURE DRIFT` error as a
signal to update the case, never to delete it.

### 2.5 What the gate does NOT catch — fix during the port

The first run passed verification on the first try, and the level **had no win
condition.** The goal was an `Area2D` with a collision shape, no script, and no
`[connection]` anywhere. Five agents and an engine gate, and nobody noticed —
because nothing checked.

The gate proves the scene *loads*. It says nothing about whether the level is
*completable*. Add these assertions to `_validate.gd`:

- Every `Area2D` named `Goal` has a script with a `body_entered` handler.
- Every `[connection]` target method exists on the target's script.
- No script declares a `class_name` that already exists in a shared library
  (the reuse check, once shared assets land).

---

## 3. What moves, what gets rewritten

Roughly all the domain knowledge ports; only the plumbing dies.

| Ports unchanged | Rewritten or dropped |
| --- | --- |
| All five skills → `.claude/skills/` | `setup_environment.py` — no container |
| `godot_verify.py` — stdlib only, importable anywhere | `create_specialists.py` → `.claude/agents/*.md` |
| `godot_project/` scaffold + `_validate.gd` | `create_coordinator.py` → a skill |
| `reference-scene/` — the worked example | `upload_skills.py` — skills live in the repo |
| `evals/` and the four briefs | `run_scene_build.py`, `download_deliverable.py` |

Skills becoming files in git rather than API uploads is a straight improvement:
versioned alongside the code they describe, no upload step, no drift between
what's attached and what's committed.

---

## 4. The roster

Five files in `.claude/agents/`. The system prompt bodies port from
`create_specialists.py` nearly verbatim.

```markdown
---
name: level-designer
description: Owns level.tscn — platform geometry, collision, spawn and
  goal placement. Give it the brief and viewport size; returns a
  complete level.tscn plus a platform table.
tools: Read, Write, Edit, Glob, Grep, Bash
model: opus
---

You are the Level Designer. You own `level.tscn` and nothing else.
...
```

Two fields carry real weight:

- **`description`** is what gets read when choosing who to spawn. The original
  agents were created without one — a genuine bug, since it makes an agent
  effectively invisible to its coordinator.
- **`tools`** is a permission boundary. The Build Validator gets read/glob/grep
  only; it triages, it doesn't patch.

Use `/agents` to author these rather than hand-writing frontmatter.

---

## 5. The coordinator becomes a skill

There is no coordinator agent locally — **the main session is the coordinator.**
So `create_coordinator.py` doesn't become a file describing a coordinator; its
prompt becomes instructions the session follows.

```markdown
---
name: build-level
description: Build a Godot 2D platformer scene from a design brief,
  verified against the local engine. Use when asked to build, generate,
  or repair a level. Takes a path to a brief, or the brief inline.
---

# Build a level

## Round 0 — build
1. Read the brief. Note the beats and anything constraining geometry.
2. Delegate to level-designer, player-controller and game-feel in a
   SINGLE message so they run in parallel. Each brief must be
   self-contained — they see none of this conversation.
3. When all three report, hand scene-integrator their outputs.

## Verify
Run `python godot_verify.py`. Do not trust its exit code alone — read
the findings. No findings is the only pass.

## Repair
1. Give the findings verbatim to build-validator. Do not pre-diagnose.
2. Dispatch its fixes to the owning specialists, parallel where
   independent.
3. Re-run verify. Stop after 3 rounds and report what is still broken.
```

Invoked as `/build-level evals/briefs/03-vertical-shaft.md`.

> **Known limit.** A skill is *instructions*, not enforcement. The session can
> skip the verify step, delegate serially, or diagnose errors itself instead of
> routing them to the validator. That flexibility is usually welcome
> interactively — but for eval sweeps or CI, where run-to-run variance is the
> enemy, use a `Workflow` script instead. It executes a fixed shape rather than
> a suggested one.
>
> **Skill for interactive work; workflow for measurement.**

---

## 6. Pitfalls carried forward

- **Briefs must be self-contained.** Subagents see none of the coordinator's
  conversation. This is the single most common way local swarms fail. It's why
  the specialist prompts repeat the file contract verbatim instead of trusting
  the coordinator to relay it.
- **Attach the format skill to everyone who writes the format.** Originally
  `godot-scene-format` went to the Scene Integrator alone. `main.tscn` came back
  correct while `level`, `player` and `pickup` all emitted deprecated
  `load_steps`. Same model, same task — only the agent holding the knowledge got
  it right. Four agents write `.tscn`; four agents need the skill.
- **Reuse needs enforcement, not encouragement.** Once a shared library exists,
  agents will confidently rewrite what already exists, because reading is harder
  than writing. Prompt for it, then assert it in `_validate.gd`.
- **Keep the flat-project contract only while it earns its place.** "Write
  exactly these six filenames" is right for a one-shot demo and wrong for a
  project with shared assets. Loosen it deliberately, not accidentally.

---

## 7. Build order

1. **Port the gate and prove it.** Copy `godot_verify.py`, `godot_project/` and
   `reference-scene/`. Run `evals/harness_regression.py`. Five green cases
   before anything else is written — this is the only step that must not be
   reordered.
2. **Add the missing assertions.** Win condition, signal-target methods. Extend
   the regression suite with a fifth fault covering an unwired goal, and watch
   it fail before you fix it.
3. **Move the skills.** Straight copy into `.claude/skills/`. Attach the format
   skill to all four `.tscn` authors.
4. **Write the roster.** Five agent files via `/agents`.
5. **Write the coordinator skill.** Then run it against `01-minimal.md` — if the
   easy brief needs a repair round, something in the port is wrong.
6. **Add per-specialist self-verification.** Each builder runs the engine on its
   own file before reporting. This is the whole point of going local; do it once
   the pipeline is otherwise working.

---

## 8. What to measure afterwards

The cloud version has exactly one successful run behind it. That is an anecdote,
not evidence, and the port is a good moment to fix that.

- **`pass@round-0`** — did the scene load *before* the repair loop rescued it.
  Everything else is masked by repairs; this is the only metric that measures
  whether the skills work.
- **Rounds to green**, and whether per-specialist self-verification actually
  reduces it. That is the port's central claim and it should be checked, not
  assumed.
- **Reuse rate**, once shared assets exist — what fraction of referenced scripts
  came from the library rather than being rewritten.

> **The question worth answering.** Nothing in the original run distinguishes
> *"the swarm worked"* from *"the skills and the engine worked, and the swarm
> came along."* A single agent holding all five skills, with the same verifier,
> might do as well and cost less. Running the eval sweep both ways would settle
> it — and it's worth knowing before treating coordinator-plus-specialists as a
> default rather than a tool.

---

*Derived from the working cloud implementation on branch
`stagehands-godot-swarm`. Calibration figures are measured against Godot 4.7.2
on macOS; the first end-to-end run cost $2.23 and passed with zero repair
rounds.*
