---
name: godot-game-feel
description: Camera, pickup and signal patterns for a Godot 4.7 2D platformer. Use whenever configuring a following camera, building Area2D collectibles, wiring signals, or adding Tween polish — covers Camera2D limits and smoothing, body_entered detection, and the queue_free rule. Trigger on any request to add a camera, pickups, collectibles, or juice to a scene.
---

# Game Feel — Camera, Pickups, Signals

## Camera2D

A camera without limits shows empty space past the level edge, which reads as
a bug. Always set all four.

```
[node name="Camera2D" type="Camera2D" parent="Player"]
position_smoothing_enabled = true
position_smoothing_speed = 6.0
limit_left = 0
limit_top = 0
limit_right = 1152
limit_bottom = 648
```

- Parent it to the **player** so it follows for free.
- Limits are the **level bounds**, from the Level Designer's platform table —
  not the viewport size, when the level is wider than one screen.
- `position_smoothing_speed`: 4 is languid, 6 is neutral, 10 is snappy. Below
  3 feels broken; above 15 there is no point smoothing.
- Set `limit_bottom` to the level floor, not lower — otherwise the camera
  drifts down into nothing when the player falls.

## Area2D pickups

```
[gd_scene format=3]

[ext_resource type="Script" path="res://pickup.gd" id="1_pickup"]

[sub_resource type="CircleShape2D" id="CircleShape2D_pickup"]
radius = 12.0

[node name="Pickup" type="Area2D"]
script = ExtResource("1_pickup")

[node name="Visual" type="ColorRect" parent="."]
offset_left = -10.0
offset_top = -10.0
offset_right = 10.0
offset_bottom = 10.0
color = Color(0.98, 0.85, 0.35, 1)

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_pickup")

[connection signal="body_entered" from="." to="." method="_on_body_entered"]
```

```gdscript
extends Area2D

signal collected

var _taken: bool = false


func _on_body_entered(body: Node2D) -> void:
    if _taken:
        return
    if not body is CharacterBody2D:
        return
    _taken = true
    collected.emit()

    # queue_free(), never free(): freeing a node while its own signal is still
    # being dispatched crashes the engine.
    var tween: Tween = create_tween()
    tween.set_parallel(true)
    tween.tween_property(self, "scale", Vector2(1.6, 1.6), 0.18)
    tween.tween_property(self, "modulate:a", 0.0, 0.18)
    tween.chain().tween_callback(queue_free)
```

Three rules with teeth:

1. **`queue_free()`, never `free()`** inside a signal handler. `free()`
   destroys the node mid-dispatch and takes the engine with it.
2. **Guard against double collection.** `body_entered` can fire twice in one
   frame with overlapping shapes; the `_taken` flag is not optional.
3. **The `method=` in a `[connection]` must exist on the target script.** A
   missing method is a *runtime* error, so it only appears when the scene
   actually boots — after everything else has passed.

## Signal syntax

`[connection]` blocks go **after all nodes** in the file:

```
[connection signal="body_entered" from="Pickup" to="Pickup" method="_on_body_entered"]
```

`from` and `to` use the same root-relative paths as `parent=`. In Godot 4,
emitting is `my_signal.emit()`, not `emit_signal("my_signal")`.

## Tuning table

| Element | Value | Why |
| --- | --- | --- |
| Camera smoothing speed | 6.0 | Follows without lagging |
| Pickup radius | 12 px | Forgiving against a 32 px player |
| Collect tween | 0.18 s | Readable, does not delay play |
| Pickup spacing | ≥ 120 px apart | Each one reads as a decision |
| Pickup height above platform | 32–48 px | Reachable while running |

## How to report

You do not own `main.tscn`. Hand the Scene Integrator literal text to paste,
and nothing else:

```
CAMERA BLOCK (parent to the Player node)
[node name="Camera2D" type="Camera2D" parent="Player"]
position_smoothing_enabled = true
position_smoothing_speed = 6.0
limit_left = 0
limit_top = 0
limit_right = 1152
limit_bottom = 648

PICKUP INSTANCES (main.tscn needs an ext_resource for res://pickup.tscn)
[node name="Pickup1" parent="." instance=ExtResource("3_pickup")]
position = Vector2(360, 432)

[node name="Pickup2" parent="." instance=ExtResource("3_pickup")]
position = Vector2(720, 324)
```
