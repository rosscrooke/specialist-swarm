---
name: godot-scene-format
description: Authoritative .tscn text format reference for Godot 4.7. Use whenever writing, assembling, or correcting a .tscn scene file by hand — covers the gd_scene header, ext_resource and sub_resource declarations, node parenting rules, script attachment, and signal connections. Trigger on any request to author a scene file, assemble a scene tree, or fix a scene that fails to load.
---

# Godot 4.7 `.tscn` Format

Written for an engine that will reject you. Every rule below has a failure
mode attached; the failure modes are what the local verifier actually reports.

## Three rules that changed in 4.6 — your training data is probably wrong

| Rule | Wrong (pre-4.6) | Correct for 4.7 |
| --- | --- | --- |
| Header | `[gd_scene load_steps=4 format=3]` | `[gd_scene format=3]` |
| Resource ids | `uid="uid://cxyz123"` on scene and ext_resource | **omit `uid` entirely** |
| Node headings | — | `unique_id=N` exists but is optional; omit it |

**`load_steps` is deprecated and ignored.** Do not compute it. Emitting it is
not fatal but it signals you are working from an old mental model.

**Never invent a `uid://`.** Godot prefers the uid over the path when both are
present, so a fabricated uid on an `ext_resource` makes the reference
unresolvable even though the path beside it is correct. Omit it and Godot
mints a real one on import.

## Anatomy, in required order

```
[gd_scene format=3]                          ← exactly one, first line

[ext_resource type="..." path="..." id="..."]  ← all ext_resources
[sub_resource type="..." id="..."]             ← all sub_resources
  <properties>

[node name="Root" type="Node2D"]               ← exactly one root, no parent=
[node name="Child" type="..." parent="."]      ← everything else
```

Order is load-bearing. A `sub_resource` must appear **before** anything that
references it, and all resource declarations come before the first `node`.

## Parenting

- The root node has **no** `parent=` key. Exactly one node may omit it.
- Direct children: `parent="."`
- Deeper nodes: a root-relative path that **excludes the root's own name** —
  `parent="Ground"`, `parent="Arm/Hand"`. Never `parent="Root/Ground"`.

*Failure mode:* two nodes without `parent=` → the scene will not load at all.

## `ext_resource` — referencing another file

```
[ext_resource type="Script" path="res://player.gd" id="1_player"]
[ext_resource type="PackedScene" path="res://level.tscn" id="2_level"]
```

`id` is an arbitrary string, unique within the file. The convention
`<n>_<name>` is readable and collision-free.

*Failure mode:* a path that does not exist produces
`Parse Error: [ext_resource] referenced non-existent resource`. Godot then
substitutes a placeholder and **keeps loading**, so the scene appears to work
while the node is silently missing. Check every path against the flat file
list before you emit.

## `sub_resource` — a resource defined inline

```
[sub_resource type="RectangleShape2D" id="RectangleShape2D_body"]
size = Vector2(32, 48)
```

Referenced as `SubResource("RectangleShape2D_body")`.

*Failure mode:* referencing an id that was never declared gives
`Parse Error: Invalid parameter. [Resource file res://player.tscn:19]` and the
whole scene fails to load — along with every scene that instances it.

## Attaching a script

```
[ext_resource type="Script" path="res://player.gd" id="1_player"]

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player")
```

*Failure mode:* if `player.gd` has a parse error, the node loads with **no
script and no error on the node itself**. The scene looks fine and does
nothing. Only compiling the script catches this.

## Instancing another scene

```
[ext_resource type="PackedScene" path="res://player.tscn" id="2_player"]

[node name="Player" parent="." instance=ExtResource("2_player")]
position = Vector2(120, 520)
```

An instanced node takes `instance=`, **not** `type=`. You may add children to
it from the parent scene (`parent="Player"`) and override its exported
properties by listing them underneath.

## Connecting a signal

```
[connection signal="body_entered" from="Pickup" to="Pickup" method="_on_body_entered"]
```

Connections go **after** all nodes. `from`/`to` use the same root-relative
paths as `parent=`. The `method` must exist on the target's script — a missing
method is a runtime error, not a load error, so it only surfaces on boot.

## Common property syntax

```
position = Vector2(576, 624)
color = Color(0.18, 0.22, 0.31, 1)
size = Vector2(1152, 48)
offset_left = -576.0            # floats need the decimal point
shape = SubResource("RectangleShape2D_ground")
script = ExtResource("1_player")
```

## Worked example — a scene that provably loads

This is the reference scene in `reference-scene/`, verified against Godot
4.7.2. When unsure, copy its shape.

```
[gd_scene format=3]

[ext_resource type="Script" path="res://player.gd" id="1_player"]

[sub_resource type="RectangleShape2D" id="RectangleShape2D_body"]
size = Vector2(32, 48)

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player")

[node name="Body" type="ColorRect" parent="."]
offset_left = -16.0
offset_top = -24.0
offset_right = 16.0
offset_bottom = 24.0
color = Color(0.96, 0.76, 0.26, 1)

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("RectangleShape2D_body")
```

Note the CollisionShape2D **has a shape assigned**. One with `shape = null` is
accepted by the loader and is completely inert at runtime — a platform you can
walk through. The verifier checks for this explicitly.

## Before you emit — the checklist

1. Header is `[gd_scene format=3]`, no `load_steps`, no `uid`.
2. Every `ext_resource` path exists in the flat project.
3. Every `SubResource("x")` has a matching `[sub_resource id="x"]` **above** it.
4. Exactly one node without `parent=`.
5. No `parent=` path includes the root node's own name.
6. Every `CollisionShape2D` has a `shape`.
7. Every `[connection]` method exists on the target script.
