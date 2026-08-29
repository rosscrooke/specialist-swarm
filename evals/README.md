# Evals

Two tiers, with very different cost profiles. Run Tier 1 constantly; run
Tier 2 when you need a number.

## Tier 1 — `harness_regression.py`

**Free. Offline. ~3 minutes. No API key.**

```bash
python evals/harness_regression.py
```

Regression-tests `godot_verify.py` itself. It rebuilds a project from
`reference-scene/`, injects one fault per detection path, and asserts the
harness still catches each.

This matters more than it looks. `godot_verify.py` is the grader for
everything else — if it silently stops detecting a fault class, every Tier 2
eval turns green and lies to you. A broken grader is worse than no grader.

The four faults are one per path:

| Fault | Caught by |
| --- | --- |
| GDScript syntax error | validator exit code + log scrape |
| bad `ext_resource` path | **log scrape only** (import stage) |
| missing `sub_resource` | validator exit code + log scrape |
| runtime null deref | **log scrape only** (boot stage) |

Two of the four are visible to exactly one stage. That is why all three stages
exist, and why removing one to "speed things up" is a silent regression.
Godot's own exit code is `0` for all four.

If a case fails with `FIXTURE DRIFT`, `reference-scene/` was edited and the
test's find/replace no longer matches — update the case, don't delete it.

## Tier 2 — `run_evals.py`

**Spends real money.** ~$2–3 per run. Refuses to start without `--yes`.

```bash
python evals/run_evals.py --yes --samples 3
python evals/run_evals.py --yes --briefs evals/briefs/01-minimal.md
```

Runs the full swarm against each brief and records:

| Metric | Why it matters |
| --- | --- |
| **`pass_at_round_0`** | **The one that counts.** Did the scene load *before* the repair loop rescued it? Everything else is masked by repairs; this measures whether the skills actually work. |
| `rounds_to_green` | Repair-loop effectiveness. |
| `cost_usd` | Session list cost. The number a CFO asks for. |
| `format_clean` | No deprecated `load_steps`, no fabricated `uid://` — what the format skill most directly controls. |

Results append to `evals/results/<timestamp>.jsonl`, so two sweeps can be
diffed across a skill change.

### The briefs

Chosen to isolate different failure modes, not to be representative:

| Brief | Stresses |
| --- | --- |
| `01-minimal` | Baseline. If this needs a repair round, the skills are broken. |
| `02-crystal-caverns` | The demo brief. Ordinary difficulty. |
| `03-vertical-shaft` | **Cross-agent agreement.** Nearly every jump is near the limit, so the Level Designer and Player Controller must reconcile real numbers rather than each assuming defaults. |
| `04-signal-heavy` | **`.tscn` format under load.** Many sub-resources, deep nesting, real signal connections — the constructs most often written wrong by hand. |

### Reading the results honestly

- **One sample per brief is noise.** These runs are non-deterministic; use
  `--samples 3` minimum before believing a difference.
- **Comparing two sweeps needs both to be ≥3 samples**, or you are comparing
  variance.
- A high `pass_at_round_0` with a low `format_clean` means the skills are
  being partly ignored while the engine happens to tolerate it — a real
  finding, and an early warning for harder scenes.

### The open question this exists to answer

`godot-scene-format` was originally attached to the Scene Integrator alone.
`main.tscn` came back correct while `level`/`player`/`pickup` all emitted the
deprecated `load_steps=N`. It is now attached to all four `.tscn` authors —
**but that change has never been measured.** A 3-sample sweep before and after
is the first thing worth spending money on.
