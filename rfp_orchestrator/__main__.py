"""CLI: python -m rfp_orchestrator [--rfp FILE] [--input FILE ...]"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .api import run_rfp
from .config import REPO_ROOT
from .events import ConsoleSink

DATA = REPO_ROOT / "synthetic-data"


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    p = argparse.ArgumentParser(description="Run the hierarchical RFP agent team.")
    p.add_argument("--rfp", type=Path, default=DATA / "rfp-acme-corp.md")
    p.add_argument(
        "--input",
        type=Path,
        action="append",
        dest="inputs",
        help="Reference file (repeatable). Default: synthetic-data/past-wins.json + product-overview.md",
    )
    p.add_argument("--instructions", default="", help="Extra instructions for the bid lead.")
    p.add_argument("--show-text", action="store_true", help="Print agent text messages too.")
    args = p.parse_args()

    inputs = args.inputs or [DATA / "past-wins.json", DATA / "product-overview.md"]
    result = asyncio.run(
        run_rfp(args.rfp, extra_inputs=inputs, instructions=args.instructions, sinks=[ConsoleSink(args.show_text)])
    )

    print("\n" + "=" * 70)
    print(result.final_text)
    print("=" * 70)
    print(f"Run {result.run_id}: ok={result.ok}, agents={len(result.agents)}, {result.duration_s:.0f}s")
    for model, u in result.usage_by_model.items():
        print(f"  {model}: in={u['input_tokens']} out={u['output_tokens']} cache_read={u['cache_read_input_tokens']}")
    for d in result.deliverables:
        print(f"  deliverable: {d}")


if __name__ == "__main__":
    main()
