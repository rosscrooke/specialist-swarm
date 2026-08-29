# Reference scene — the known-good example

A minimal but complete 2D platformer scene set, hand-written and verified
against Godot 4.7.2. It exists for two reasons:

1. **It is the worked example inside `skills/godot-scene-format/SKILL.md`.**
   Every `.tscn` convention the swarm is asked to follow is demonstrated here
   in a file that provably loads.
2. **It is the fixture that calibrated `godot_verify.py`.** The harness's
   error signatures and noise filters were derived by taking these files,
   breaking them four ways, and diffing the logs.

These files are deliberately **not** in `godot_project/` — that directory
starts empty apart from the two harness-owned files, so a swarm run that
produces nothing cannot be mistaken for a swarm run that succeeded.

To check the harness still works after changing it:

```bash
cp reference-scene/*.tscn reference-scene/*.gd godot_project/
python godot_verify.py            # expect PASS, exit 0
```
