"""
Download every file produced by a Deal Desk session.

By default reads the session ID from `.last_session_id` (written by
run_deal_desk.py). You can also pass the session ID as a CLI argument
to grab files from any older session.

Usage:
    python download_deliverable.py                       # last run
    python download_deliverable.py sesn_01ABC...         # specific session
"""

import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


OUTPUT_DIR = Path("godot_project")


def main() -> None:
    # Resolve session ID
    if len(sys.argv) > 1:
        session_id = sys.argv[1].strip()
    else:
        last = Path(".last_session_id")
        if not last.exists():
            raise SystemExit(
                "No session ID provided and `.last_session_id` not found.\n"
                "Usage: python download_deliverable.py <session_id>"
            )
        session_id = last.read_text().strip()

    client = Anthropic()

    print(f"Listing files for session {session_id}...")
    # `scope_id` filters to files associated with that session
    files = client.beta.files.list(
        scope_id=session_id,
        betas=["managed-agents-2026-04-01"],
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    count = 0
    for f in files.data:
        out_path = OUTPUT_DIR / f.filename
        print(f"  downloading {f.filename} ({f.id})")
        content = client.beta.files.download(f.id)
        content.write_to_file(str(out_path))
        print(f"    -> {out_path}")
        count += 1

    if count == 0:
        print("\nNo files found on that session.")
        print("Check the session in the Console:")
        print(f"  https://platform.claude.com/sessions/{session_id}")
    else:
        print(f"\nDownloaded {count} file(s) to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
