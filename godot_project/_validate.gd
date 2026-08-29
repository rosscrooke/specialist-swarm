extends SceneTree

# ============================================================================
#  OWNED BY THE HARNESS — the swarm must never write this file.
#
#  Stage 2 of godot_verify.py. Godot's own exit codes are unreliable (a parse
#  error exits 0), so this script produces an exit code we control: it loads
#  and instantiates every scene in the project and fails loudly on anything
#  that does not come back a live Node.
#
#  Machine-readable output: every problem is printed as a single line
#      VALIDATE_FAIL|<scene path>|<what went wrong>
#  so the harness can parse findings without guessing at Godot's phrasing.
# ============================================================================

const REQUIRED_SCENES: Array[String] = ["res://main.tscn"]

func _init() -> void:
	var failures: int = 0
	var scenes: Array[String] = _find_scenes("res://")
	scenes.sort()

	for required: String in REQUIRED_SCENES:
		if not scenes.has(required):
			print("VALIDATE_FAIL|", required, "|required scene is missing from the project")
			failures += 1

	# Scripts first: a .gd that fails to parse leaves nodes with a silently
	# null script rather than raising, so scene checks alone will not see it.
	var scripts: Array[String] = _find_files("res://", ".gd")
	scripts.sort()
	for script_path: String in scripts:
		if script_path == "res://_validate.gd":
			continue
		failures += _check_script(script_path)

	for scene_path: String in scenes:
		failures += _check_scene(scene_path)

	print("VALIDATE_SUMMARY|scenes=", scenes.size(), "|scripts=", scripts.size(), "|failures=", failures)
	quit(1 if failures > 0 else 0)


func _check_script(script_path: String) -> int:
	# A GDScript with a parse error still loads as a Resource and still reports
	# `is Script` — only can_instantiate() actually goes false. Checking for
	# null here would silently pass every broken script in the project.
	var res: Resource = ResourceLoader.load(script_path, "Script", ResourceLoader.CACHE_MODE_IGNORE)
	if res == null or not (res is Script):
		print("VALIDATE_FAIL|", script_path, "|script could not be loaded at all")
		return 1
	if not (res as Script).can_instantiate():
		print("VALIDATE_FAIL|", script_path, "|script failed to compile (see the Parse Error above for the line)")
		return 1
	return 0


func _check_scene(scene_path: String) -> int:
	# ResourceLoader rather than load() so a bad scene returns null instead of
	# aborting the run, letting us report every broken scene in one pass.
	var packed: Resource = ResourceLoader.load(scene_path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if packed == null:
		print("VALIDATE_FAIL|", scene_path, "|failed to load (malformed .tscn or missing ext_resource)")
		return 1
	if not (packed is PackedScene):
		print("VALIDATE_FAIL|", scene_path, "|loaded but is not a PackedScene")
		return 1

	var scene: PackedScene = packed as PackedScene
	if not scene.can_instantiate():
		print("VALIDATE_FAIL|", scene_path, "|PackedScene cannot be instantiated")
		return 1

	var root: Node = scene.instantiate()
	if root == null:
		print("VALIDATE_FAIL|", scene_path, "|instantiate() returned null")
		return 1

	var problems: int = _check_tree(scene_path, root, root)
	root.free()
	return problems


func _check_tree(scene_path: String, node: Node, root: Node) -> int:
	var problems: int = 0

	# A script that failed to compile leaves the node with a null script
	# reference rather than raising, so check it explicitly.
	var script_ref: Variant = node.get_script()
	if script_ref != null and not (script_ref is Script):
		print("VALIDATE_FAIL|", scene_path, "|node '", root.get_path_to(node),
			"' has an unusable script reference")
		problems += 1

	# Collision shapes with no shape resource are silently inert at runtime —
	# the single most common way a generated platformer looks right and isn't.
	if node is CollisionShape2D:
		var cs: CollisionShape2D = node as CollisionShape2D
		if cs.shape == null:
			print("VALIDATE_FAIL|", scene_path, "|CollisionShape2D '", root.get_path_to(node),
				"' has no shape resource assigned")
			problems += 1

	for child: Node in node.get_children():
		problems += _check_tree(scene_path, child, root)
	return problems


func _find_scenes(dir_path: String) -> Array[String]:
	return _find_files(dir_path, ".tscn")


func _find_files(dir_path: String, suffix: String) -> Array[String]:
	var found: Array[String] = []
	var dir: DirAccess = DirAccess.open(dir_path)
	if dir == null:
		return found
	dir.list_dir_begin()
	var entry: String = dir.get_next()
	while entry != "":
		if entry.begins_with("."):
			entry = dir.get_next()
			continue
		var full: String = dir_path.path_join(entry)
		if dir.current_is_dir():
			found.append_array(_find_files(full, suffix))
		elif entry.ends_with(suffix):
			found.append(full)
		entry = dir.get_next()
	dir.list_dir_end()
	return found
