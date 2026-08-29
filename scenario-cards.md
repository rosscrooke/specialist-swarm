# Scenario Cards — Option 3 (Godot)

Each team picks ONE scenario. Each is shaped the same way: a coordinator who
orchestrates, 3–5 specialists who own lanes, and — the part that makes this
track different — **a local engine that decides whether the work is correct.**

Different teams should pick different cards.

---

## Card A — 2D Platformer Level (default scenario, fully wired in starter code)

**Coordinator:** "Technical Director"
- Reads a level brief
- Fans work out to three builders in parallel, then has an integrator assemble
- On a repair round, routes real Godot errors through the Build Validator

**Specialists:**
1. **Level Designer** (skill: godot-level-layout) — platform geometry, collision, spawn and goal placement
2. **Player Controller** (skill: gdscript-character-body-2d) — CharacterBody2D movement, coyote time, jump buffering
3. **Game Feel Specialist** (skill: godot-game-feel) — camera limits and smoothing, Area2D pickups, signal wiring
4. **Scene Integrator** (skill: godot-scene-format) — assembles main.tscn; owns .tscn format correctness
5. **Build Validator** (skill: godot-error-triage) — triages real engine output and names the owning specialist

**The trigger:** `synthetic-data/level-brief-crystal-caverns.md`

**The deliverable:** A playable scene in `godot_project/`, verified by Godot 4.7

**The gate:** import → instantiate → boot, all headless, all locally

---

## Card B — UI / HUD Screen

**Coordinator:** "UX Lead"
- Reads a screen spec and produces a Control-node tree that lays out correctly

**Specialists:**
1. **Layout** — anchors, containers, margins, responsive behaviour
2. **Theming** — a Theme resource, fonts, colours, style boxes
3. **Interaction** — button signals, focus order, keyboard navigation
4. **Scene Integrator** — assembles the Control tree
5. **Build Validator** — same role as Card A

**Why it is interesting:** Control-node layout is extremely sensitive to
anchor and container correctness, so the specialist split (layout vs theming
vs interaction) is genuinely load-bearing rather than cosmetic.

**Extra work:** `_validate.gd` should additionally assert that no Control has
a zero size after one layout pass — the characteristic failure of a bad
anchor setup, and invisible to the import stage.

---

## Card C — Procedural Level Generator

**Coordinator:** "Tools Lead"
- Produces a GDScript *tool* that generates levels, rather than a level

**Specialists:**
1. **Generation Algorithm** — the placement/room algorithm
2. **Constraint Checker** — guarantees every generated level is completable
3. **Godot Integration** — `@tool` script, EditorPlugin wiring
4. **Build Validator** — same role as Card A

**Why it is interesting:** the deliverable is a tool, so verification means
running the generator N times headlessly and asserting every output is valid.
The hardest and most impressive of the three.

**Extra work:** the verify stage becomes a loop over generated seeds rather
than a single scene check.

---

## Picking guidance

| If your team is... | Pick |
| --- | --- |
| Wants the cleanest path | A (platformer — code is ready, and it is playable) |
| Most relatable to enterprise app clients | B (UI — this is the shape of real client work) |
| Wants the hardest technical demo | C (generator — verification over N runs) |
| Wants the best two-minute demo | A — nothing beats playing the thing on stage |
