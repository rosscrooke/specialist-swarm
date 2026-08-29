extends CharacterBody2D

const SPEED: float = 260.0
const JUMP_VELOCITY: float = -420.0
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
