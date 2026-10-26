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


# Map each skill directory name to the key of the specialist that should get it.
SKILL_TO_SPECIALIST: dict[str, str] = {}


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    specialist_ids_path = Path(".specialist_ids.json")
    if not specialist_ids_path.exists():
        raise SystemExit("Run create_specialists.py first.")
    specialist_ids = json.loads(specialist_ids_path.read_text())

    client = Anthropic()

    # List existing custom skills so we can detect and reuse any prior uploads.
    # Skill display titles must be unique, so reuse previously uploaded skills.
    print("Checking for existing skills...")
    existing_by_title: dict[str, str] = {}
    for page in client.beta.skills.list(source="custom"):
        existing_by_title[page.display_title] = page.id

    uploaded: dict[str, str] = {}

    for skill_name, specialist_key in SKILL_TO_SPECIALIST.items():
        skill_dir = Path("skills") / skill_name
        if not (skill_dir / "SKILL.md").exists():
            raise SystemExit(f"Missing skills/{skill_name}/SKILL.md")
        if specialist_key not in specialist_ids:
            raise SystemExit(
                f"Unknown specialist key {specialist_key!r} for skill {skill_name!r}. "
                "Check .specialist_ids.json and SKILL_TO_SPECIALIST."
            )

        display_title = skill_name.replace("-", " ").title()

        # 1. Upload the skill (or reuse if one already exists with this title)
        if display_title in existing_by_title:
            skill_id = existing_by_title[display_title]
            print(f"Reusing existing skill: {skill_name} ({skill_id})")
            uploaded[skill_name] = skill_id
        else:
            print(f"Uploading skill: {skill_name}...")
            skill = client.beta.skills.create(
                display_title=display_title,
                files=files_from_dir(str(skill_dir)),
            )
            uploaded[skill_name] = skill.id
            print(f"  -> {skill.id}")

        # 2. Attach to the matching specialist by updating its skills array
        specialist_id = specialist_ids[specialist_key]
        skill_id = uploaded[skill_name]
        print(f"  attaching to specialist `{specialist_key}` ({specialist_id})...")

        current = client.beta.agents.retrieve(specialist_id)
        # Avoid duplicate attachment on re-run
        already_attached = any(
            s.get("skill_id") == skill_id for s in (current.skills or [])
        )
        if already_attached:
            print(f"  already attached ✓ (skipping)")
            continue

        new_skills = list(current.skills or []) + [
            {"type": "custom", "skill_id": skill_id, "version": "latest"}
        ]
        client.beta.agents.update(
            specialist_id,
            version=current.version,
            skills=new_skills,
        )
        print(f"  attached ✓")

    Path(".skill_ids.json").write_text(json.dumps(uploaded, indent=2))
    print(f"\nUploaded and attached {len(uploaded)} skills.")
    print("Next: python run_swarm.py \"Describe the task for the swarm\"")


if __name__ == "__main__":
    main()
