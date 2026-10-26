"""
Create the cloud Environment used by Managed Agents sessions.

Safe to run multiple times — if `.environment_id` already exists, it's reused.

Usage:
    python setup_environment.py
"""

import os
from pathlib import Path

from anthropic import Anthropic


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY before running.")

    env_path = Path(".environment_id")
    if env_path.exists():
        existing = env_path.read_text().strip()
        print(f"Environment already exists: {existing}")
        print("(remove .environment_id if you want to provision a new one)")
        return

    client = Anthropic()
    environment = client.beta.environments.create(
        name="specialist-swarm-env",
        config={
            "type": "cloud",
            "networking": {"type": "unrestricted"},
        },
    )
    env_path.write_text(environment.id)
    print(f"Environment created: {environment.id}")


if __name__ == "__main__":
    main()
