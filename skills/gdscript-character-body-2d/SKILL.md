---
name: gdscript-character-body-2d
description: CharacterBody2D platformer controller patterns for Godot 4.7 GDScript. Use whenever writing player movement — covers move_and_slide, gravity from ProjectSettings, coyote time, jump buffering, acceleration and friction tuning, and the GDScript typing rules that cause silent parse failures. Trigger on any request to write a player controller, tune jump feel, or fix movement code.
---

# CharacterBody2D Controller

## The input contract

`project.godot` already maps these. Use these exact names; do not invent your
own and do not try to add actions at runtime.

| Action | Keys |
| --- | --- |
| `move_left` | Left, A |
| `move_right` | Right, D |
| `jump` | Space, W, Up |

Read the axis with `Input.get_axis("move_left", "move_right")` — it returns
−1.0 to 1.0 and handles both keys held at once.

## GDScript rules that cost a build round

**A parse error does not raise.** The script silently loads as a node with no
script attached; the scene appears to load and simply does nothing. Assume no
runtime feedback will tell you — get it right by inspection.

| Trap | Wrong | Right |
| --- | --- | --- |
| Inference on an untyped value | `var p := "input/" + action` where `action` came from a Dictionary | `var p: String = "input/" + str(action)` |
| Typed loop over untyped container | `for k in dict:` then using `k` as String | `for k: String in dict.keys():` |
| Integer division surprise | `var half = size / 2` on ints | `var half: float = size / 2.0` |
| Float literals in Vector2 | `Vector2(1152, 48)` is fine | but `offset_left = -96` should be `-96.0` in .tscn |

`:=` is only safe when the right-hand side has a known static type. When in
doubt, annotate explicitly — it costs nothing and cannot fail.

## Gravity

Read it from project settings rather than hardcoding, so the level designer's
reachability maths and yours agree:

```gdscript
var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity", 980.0)
```

## The controller

```gdscript
extends CharacterBody2D

const SPEED: float = 260.0
const JUMP_VELOCITY: float = -420.0      # negative is up
const ACCELERATION: float = 1800.0
const FRICTION: float = 2200.0
const COYOTE_TIME: float = 0.10
const JUMP_BUFFER: float = 0.12

var _gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity", 980.0)
var _coyote_left: float = 0.0
var _buffer_left: float = 0.0


func _physics_process(delta: float) -> void:
    if is_on_floor():
        _coyote_left = COYOTE_TIME
    else:
        _coyote_left = maxf(_coyote_left - delta, 0.0)
        velocity.y += _gravity * delta

    if Input.is_action_just_pressed("jump"):
        _buffer_left = JUMP_BUFFER
    else:
        _buffer_left = maxf(_buffer_left - delta, 0.0)

    if _buffer_left > 0.0 and _coyote_left > 0.0:
        velocity.y = JUMP_VELOCITY
        _buffer_left = 0.0
        _coyote_left = 0.0

    var direction: float = Input.get_axis("move_left", "move_right")
    if absf(direction) > 0.01:
        velocity.x = move_toward(velocity.x, direction * SPEED, ACCELERATION * delta)
    else:
        velocity.x = move_toward(velocity.x, 0.0, FRICTION * delta)

    move_and_slide()
```

Notes on why it is shaped this way:

- **`move_and_slide()` takes no arguments in Godot 4** and reads `velocity`
  directly. Passing a vector is the Godot 3 signature and will not parse.
- **Coyote time** lets the player jump for a beat after walking off a ledge.
- **Jump buffering** honours a jump pressed just before landing. Both are
  what separate "responsive" from "unfair"; neither is optional.
- Gravity is applied only when airborne, so `is_on_floor()` stays reliable.
- `move_toward` gives acceleration and friction in one call.

## Tuning table

| Feel | SPEED | JUMP_VELOCITY | ACCELERATION | FRICTION |
| --- | --- | --- | --- | --- |
| Floaty / exploratory | 200 | −380 | 1200 | 1400 |
| Balanced (default) | 260 | −420 | 1800 | 2200 |
| Twitchy / precise | 320 | −460 | 2600 | 3200 |
| Heavy / deliberate | 220 | −500 | 900 | 1800 |

Raising `JUMP_VELOCITY` magnitude raises the ceiling the level designer can
use. Always report the resulting numbers.

## The player scene

Root `CharacterBody2D`, a `ColorRect` for the body, a `CollisionShape2D` with
a real shape. The player is **32 wide by 48 tall** — the level layout assumes
it.

## How to report

End your reply with exactly this, so the Level Designer can check
reachability without reading your file:

```
CONTROLLER TUNING
speed:            260 px/s
jump velocity:    -420
gravity:          980 (from ProjectSettings)
peak jump height: 90 px      = jump_velocity^2 / (2 * gravity)
jump distance:    220 px     = speed * (2 * jump_velocity / gravity)
player size:      32 x 48
```
