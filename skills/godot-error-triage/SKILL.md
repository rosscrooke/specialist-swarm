---
name: godot-error-triage
description: Lookup table from Godot 4.7 error output to root cause, owning specialist, and the fix. Use whenever triaging findings produced by running Godot against generated scene files — covers parse errors, missing resources, uninstantiable scenes, and runtime null references. Trigger on any request to diagnose a Godot build failure or dispatch scene fixes to a specialist.
---

# Godot Error Triage

Every signature below was observed in real Godot 4.7.2 output. The verifier
reports findings tagged by stage; the stage narrows the cause before you read
the message.

## What the stages mean

| Stage | What ran | What it can catch |
| --- | --- | --- |
| `[import]` | resource import of the whole project | malformed `.tscn`, bad `ext_resource` paths, GDScript parse errors |
| `[validate]` | every scene loaded and instantiated | scenes that fail to load or instantiate, scripts that fail to compile, collision shapes with no shape |
| `[boot]` | the main scene actually running | runtime faults only — null references, bad node paths, bad signal methods |

**Godot's exit code is meaningless.** A fatal parse error exits 0. A finding
is the only evidence of a problem, and no findings is the only pass.

## The table

| Error text | Root cause | Owner | Fix |
| --- | --- | --- | --- |
| `Parse Error: Expected closing ")" after call arguments.` | GDScript syntax error at the named line | Player Controller (or whoever owns the .gd) | Fix the syntax at `file:line`. |
| `Parse Error: Cannot infer the type of "x" variable because the value doesn't have a set type.` | `:=` used on a value with no static type — commonly a Dictionary/Array element | Player Controller | Replace `var x := ...` with an explicit `var x: Type = ...`. |
| `Failed to load script "res://f.gd" with error "Parse error".` | Same defect as the line above it | same | Do not treat as a separate defect. |
| `script failed to compile` (from `[validate]`) | The verifier's own confirmation of a parse error | same | Duplicate of the parse error; fix once. |
| `Parse Error: [ext_resource] referenced non-existent resource at: res://x.tscn` | A path in `ext_resource` points at a file nobody wrote | Scene Integrator | Correct the path, or get the missing file written. Check for typos against the flat file list. |
| `Cannot open file 'res://x.tscn'.` / `Failed loading resource: res://x.tscn` | Same defect | Scene Integrator | Duplicate; fix once. |
| `Parse Error: Invalid parameter. [Resource file res://x.tscn:19]` | `SubResource("id")` references an id never declared, or declared *after* use | Scene Integrator | Declare the `[sub_resource]` with that exact id, above the node that uses it. |
| `failed to load (malformed .tscn or missing ext_resource)` | The scene could not be loaded at all | Scene Integrator | Usually downstream of the row above — find the real parse error first. |
| `PackedScene cannot be instantiated` | Structural problem: no root, or two nodes lacking `parent=` | Scene Integrator | Exactly one node with no `parent=`. |
| `CollisionShape2D 'X' has no shape resource assigned` | Node has no `shape = SubResource(...)` | Level Designer (level) / Player Controller (player) | Declare a shape sub_resource and assign it. **Not** cosmetic: the body is inert, so the player falls through. |
| `Cannot call method 'x' on a null value.` | `get_node()`/`get_node_or_null()` returned null — the node path does not match the tree | whoever owns the script | Correct the node path, or guard the call. Check the path against the Scene Integrator's tree outline. |
| `Invalid access to property or key 'x' on a base object of type 'Nil'` | Same class of defect | same | As above. |
| `Attempt to call function 'x' in base 'null instance'` | Same class of defect | same | As above. |
| `Node not found: "X"` | Node path in a script or `[connection]` does not resolve | Scene Integrator + script owner | Reconcile the path with the actual tree. |
| `emit_signal: Error calling method from signal 'body_entered'` | Signal wired to a method that does not exist | Game Feel Specialist | Add the method, or fix the `method=` name in the `[connection]`. |

## Collapsing duplicates

One defect routinely produces three to seven findings. Before dispatching:

- A GDScript parse error appears in `[import]` **and** `[validate]`, plus a
  `Failed to load script` line. That is **one** defect.
- A bad `ext_resource` path produces `Cannot open file`, `Failed loading
  resource`, and `[ext_resource] referenced non-existent resource`. **One**
  defect.
- A broken `player.tscn` cascades into `main.tscn` failing to load, because
  main instances player. Fix the leaf, not the root — `main.tscn` is usually
  innocent.

**Fix the leaf first.** If both `player.tscn` and `main.tscn` appear, the
player is almost always the real defect and main is collateral.

## How to flag

Use exactly this format, one block per distinct defect:

```
DEFECT 1 — player.gd does not compile
Findings: 1, 2, 3
File: res://player.gd
Cause: Line 32 calls Input.get_axis with a missing comma and closing paren.
Owner: Player Controller
Fix: Change line 32 to  var direction: float = Input.get_axis("move_left", "move_right")
```

Then close with a single dispatch line:

```
DISPATCH: Player Controller -> player.gd; Scene Integrator -> main.tscn
```
