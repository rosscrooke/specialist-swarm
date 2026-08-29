"""
Upload each skill in skills/ via the Skills API and attach to the right
specialist agent.

Uses `files_from_dir` (from anthropic.lib) to package the skill directory.
Each skill bundle must contain a SKILL.md at its root with proper YAML
frontmatter (`name` and `description`).

Usage:
    python upload_skills.py
"""

import json
import os
from pathlib import Path

from anthropic import Anthropic
from anthropic.lib import files_from_dir
from dotenv import load_dotenv

load_dotenv()


# Map skill directory name → the specialist keys that should get it.
# Keys must match those written by create_specialists.py.
#
# godot-scene-format goes to EVERY agent that writes a .tscn, not just the
# integrator. When it was attached to the integrator alone, main.tscn came
# back correct while level/player/pickup all emitted the deprecated
# `load_steps=N` — the authors simply did not have the rules.
SKILL_TO_SPECIALISTS = {
    "godot-scene-format":         ["integrator", "level", "player", "game_feel"],
    "godot-level-layout":         ["level"],
    "gdscript-character-body-2d": ["player"],
    "godot-game-feel":            ["game_feel"],
    "godot-error-triage":         ["validator"],
}


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    specialist_ids_path = Path(".specialist_ids.json")
    if not specialist_ids_path.exists():
        raise SystemExit("Run create_specialists.py first.")
    specialist_ids = json.loads(specialist_ids_path.read_text())

    client = Anthropic()

    # List existing custom skills so we can detect and reuse any prior uploads.
    # Skills API enforces a unique display_name, so retrying with the same name
    # would otherwise fail. Idempotent retry is essential for hackathon dev loops.
    print("Checking for existing skills...")
    existing_by_title: dict[str, str] = {}
    for page in client.beta.skills.list(source="custom"):
        existing_by_title[page.display_name] = page.id

    uploaded: dict[str, str] = {}

    for skill_name, specialist_keys in SKILL_TO_SPECIALISTS.items():
        skill_dir = Path("skills") / skill_name
        if not (skill_dir / "SKILL.md").exists():
            print(f"  Skipping {skill_name} — no SKILL.md found")
            continue

        display_name = skill_name.replace("-", " ").title()

        # 1. Upload the skill (or reuse if one already exists with this title)
        if display_name in existing_by_title:
            skill_id = existing_by_title[display_name]
            print(f"Reusing existing skill: {skill_name} ({skill_id})")
            uploaded[skill_name] = skill_id
        else:
            print(f"Uploading skill: {skill_name}...")
            skill = client.beta.skills.create(
                display_name=display_name,
                files=files_from_dir(str(skill_dir)),
            )
            uploaded[skill_name] = skill.id
            print(f"  -> {skill.id}")

        # 2. Attach to every specialist that needs it
        skill_id = uploaded[skill_name]
        for specialist_key in specialist_keys:
            specialist_id = specialist_ids[specialist_key]
            current = client.beta.agents.retrieve(specialist_id)

            def attached_id(entry) -> str | None:
                if isinstance(entry, dict):
                    return entry.get("skill_id")
                return getattr(entry, "skill_id", None)

            if any(attached_id(e) == skill_id for e in (current.skills or [])):
                print(f"  `{specialist_key}` already attached ✓")
                continue

            client.beta.agents.update(
                specialist_id,
                version=current.version,
                skills=list(current.skills or [])
                + [{"type": "custom", "skill_id": skill_id, "version": "latest"}],
            )
            print(f"  attached to `{specialist_key}` ✓")

    Path(".skill_ids.json").write_text(json.dumps(uploaded, indent=2))
    print(f"\nUploaded {len(uploaded)} skills and attached them to specialists.")
    print("Next: python create_coordinator.py, then python run_scene_build.py")


if __name__ == "__main__":
    main()
