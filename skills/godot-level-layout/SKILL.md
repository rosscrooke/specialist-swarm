---
name: godot-level-layout
description: Platform geometry rules for a texture-free Godot 4 2D platformer. Use whenever laying out a level — covers the StaticBody2D/ColorRect platform idiom, the 1152x648 coordinate budget, jump-reachability spacing, collision layers, and spawn and goal placement. Trigger on any request to design a level, place platforms, or check that a level is traversable.
---

# 2D Level Layout

## The platform idiom — no textures, no TileMapLayer

This project ships no image assets, so every platform is built from three
nodes. **Do not use TileMapLayer**: it serialises tiles as a packed integer
array bound to a TileSet resource that needs a texture.

```
[sub_resource type="RectangleShape2D" id="RectangleShape2D_ledge"]
size = Vector2(192, 24)

[node name="LedgeA" type="StaticBody2D" parent="."]
position = Vector2(360, 480)

[node name="Visual" type="ColorRect" parent="LedgeA"]
offset_left = -96.0
offset_top = -12.0
offset_right = 96.0
offset_bottom = 12.0
color = Color(0.31, 0.42, 0.58, 1)

[node name="CollisionShape2D" type="CollisionShape2D" parent="LedgeA"]
shape = SubResource("RectangleShape2D_ledge")
```

Three things must agree or the level lies to the player:

1. The `RectangleShape2D` `size` is the **full** width and height.
2. The `ColorRect` offsets are **half** that, centred on zero — a 192x24
   platform is `offset_left = -96`, `offset_right = 96`, `offset_top = -12`,
   `offset_bottom = 12`.
3. The `StaticBody2D` `position` is the platform's **centre**.

A ColorRect that does not match its collision shape is the most common
"looks right, plays wrong" bug. Reuse one `sub_resource` across platforms of
identical size rather than declaring near-duplicates.

## The coordinate budget

Viewport is **1152 x 648**, origin top-left, **+y is down**.

| Thing | Sensible range |
| --- | --- |
| Ground surface | y = 600–624 |
| Lowest platforms | y = 470–520 |
| Mid platforms | y = 340–420 |
| High platforms | y = 200–300 |
| Ceiling — never place above | y = 120 |
| Playable width | x = 0–1152 (single screen) or up to 2304 (scrolling) |

If you exceed 1152 in x, say so in your report — the camera needs matching
`limit_right`.

## Reachability — the numbers that matter

With the default controller (jump velocity −420, gravity 980, speed 260):

| Quantity | Value |
| --- | --- |
| Peak jump height | ~90 px |
| Time to apex | ~0.43 s |
| Horizontal distance in a full jump | ~220 px |

Design against these, with margin:

| Gap type | Safe | Tight (deliberate challenge) | Impossible |
| --- | --- | --- | --- |
| Vertical rise between platforms | ≤ 64 px | 65–80 px | > 85 px |
| Horizontal gap | ≤ 150 px | 150–190 px | > 200 px |
| Rise **and** gap together | ≤ 48 px rise + ≤ 120 px gap | — | anything near both limits |

**Never combine a near-limit rise with a near-limit gap.** The two budgets
share one jump arc; maxing both makes the jump impossible even though each
number looks fine alone.

If the Player Controller reports different tuning numbers, recompute:
peak height = `jump_velocity² / (2 × gravity)`.

## Collision layers

Keep it simple. Default layer 1 for everything static, and let the player
occupy layer 1 too. Only reach for separate layers when you have hazards that
must not collide with pickups.

## Spawn and goal

- **Spawn**: on solid ground, at least 48 px above the platform surface, and
  at least 64 px from any wall. Never mid-air — the player starts falling and
  the first jump feels broken.
- **Goal**: reachable, but requiring at least three distinct jumps from spawn.
  Placing it on the highest platform is conventional and reads clearly.
- The player is 32 x 48. A platform narrower than 64 px is a precision landing;
  use those deliberately, not by accident.

## How to report your layout

The other specialists cannot read your file. End your reply with this table
so the camera and reachability can be checked without it:

```
PLATFORM TABLE
name        centre (x,y)     size (w,h)
Ground      (576, 624)       (1152, 48)
LedgeA      (360, 480)       (192, 24)
LedgeB      (720, 372)       (192, 24)

SPAWN: (120, 520)
GOAL:  (980, 260)
LEVEL BOUNDS: x 0..1152, y 0..648
LONGEST JUMP REQUIRED: 160 px horizontal, 62 px rise  (within budget)
```
