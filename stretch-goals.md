# Stretch Goals — Option 3 (Godot)

Pick at least one. S1 and S4 are the ones that make the demo sing.

---

## Tier 1 — Make the swarm smarter

### S1. The Playtest Critic
Run `python stretch_playtest_subagent.py`. This adds a sixth agent that judges
whether the level is *fun and fair* — reasoning from the platform table and
the controller's tuning numbers to check that every required jump is actually
possible, that the level teaches before it tests, and that rewards are visible
before the player commits.

**Why this lands:** it draws the line the whole track is about. The engine
answers "does it load?"; the critic answers "is it any good?". Two different
kinds of verification, and clients need both.

### S2. Make the level brief yours
Replace `synthetic-data/level-brief-crystal-caverns.md` with a brief for a
game your team actually wants to see. The swarm is not tuned to the sample.

**Why this lands:** it proves the pipeline is general, not a demo rigged to
one input.

---

## Tier 2 — Harden the loop

### S3. TileMapLayer instead of coloured rectangles
The starter deliberately uses `StaticBody2D` + `ColorRect` platforms, because
TileMapLayer serialises tiles as a packed integer array bound to a TileSet
texture — a high-failure-rate surface for text authoring, and it needs a
binary asset. Add a generated 4-tile PNG to the scaffold and extend the
`godot-scene-format` skill with the `tile_data = PackedInt32Array(...)`
encoding.

**Why this lands:** it is the honest hard version, and it will teach you more
about where LLM scene authoring actually breaks than anything else here.

### S4. Show the repair loop failing, then converging
Run once, hand-corrupt a line of the generated `player.gd`, and re-run with
`--max-rounds 1`. Watch the error reach the swarm and come back patched.

**Why this lands:** the strongest two minutes in the deck. It is the moment
the audience realises the agents are getting ground truth, not guessing.

### S5. Screenshot the result
Headless Godot uses a dummy rasteriser and renders nothing, so this needs a
real display driver rather than `--headless`. Get a PNG out and attach it to
the run.

**Why this lands:** closes the loop visually — and a screenshot in the
transcript is what makes the artefact shareable.

---

## Tier 3 — Wire it to the real world

### S6. Skills from the repo instead of uploads
Mount this repository as a session resource and let Godot skills load from
its root `.claude/skills` directory, so a skill edit ships with a commit
instead of an upload script.

**Why this lands:** this is how clients will actually version agent knowledge.

### S7. A regression suite
Keep every brief you run in `synthetic-data/`, and add a script that runs all
of them and reports the pass rate. Now a change to a skill has a measurable
effect.

**Why this lands:** turns prompt-tinkering into engineering. This is the
single most valuable thing to take back to a client.

### S8. Cost instrumentation
Read `usage.list_cost` off the session and print cost per successful scene,
broken down by round. Compare `SWARM_VALIDATOR_MODEL=claude-haiku-4-5`
against the Opus default.

**Why this lands:** every client asks "what does this cost to run". Have the
number.

---

## Tier 4 — For the showoffs

### S9. The voting pattern
Spawn three Level Designers with different personalities (conservative /
balanced / cruel) and have the Playtest Critic pick a winner.

### S10. Close the loop entirely
Feed the Playtest Critic's verdict back as a new brief and let the swarm
iterate on its own level until the critic says SHIP IT. Set a session budget
before you try this.

---

## Picking guidance

| If your team has 20 minutes | Pick |
| --- | --- |
| Best demo punchline | S4 (watch it repair itself) |
| Best "we should build this" outcome | S7 (regression suite) |
| Best answer to a CFO | S8 (cost per scene) |
| Hardest, most instructive | S3 (TileMapLayer) |
