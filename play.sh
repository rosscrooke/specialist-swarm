#!/usr/bin/env bash
# Launch the scene the swarm built.
#   ./play.sh        run the game
#   ./play.sh -e     open it in the Godot editor instead
set -euo pipefail
cd "$(dirname "$0")"
GODOT="${GODOT_BIN:-$HOME/Downloads/Godot.app/Contents/MacOS/Godot}"
[ -x "$GODOT" ] || { echo "Godot not found at $GODOT — set GODOT_BIN" >&2; exit 1; }
exec "$GODOT" "$@" --path godot_project
