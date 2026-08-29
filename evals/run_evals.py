"""
Tier 2 eval — end-to-end measurement of the Stagehands swarm.

THIS SPENDS REAL MONEY. Roughly $2-3 per run; a 4-brief x 3-sample sweep is
~$30-40 and a couple of hours. It refuses to start without --yes.

WHAT IT MEASURES
----------------
pass@round-0      Did the scene load BEFORE the repair loop rescued it?
                  This is the metric that matters. Everything else is masked
                  by repairs; this one measures whether the SKILLS work.
rounds_to_green   How many repair rounds were needed (null = never passed).
cost_usd          Session list cost, per run.
format_clean      Static check: no deprecated `load_steps`, no fabricated
                  `uid://`. Cheap, and it is the thing the skills most
                  directly control.

Results append to evals/results/<timestamp>.jsonl so two sweeps can be
compared after a skill change. One sample per brief is noise — use >= 3.

Usage:
    python evals/run_evals.py --yes                      # all briefs, 1 sample
    python evals/run_evals.py --yes --samples 3
    python evals/run_evals.py --yes --briefs evals/briefs/01-minimal.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from anthropic import Anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

import godot_verify  # noqa: E402
import run_scene_build as swarm  # noqa: E402

load_dotenv(REPO / ".env")
sys.stdout.reconfigure(line_buffering=True)

RESULTS_DIR = REPO / "evals" / "results"
PROJECT_DIR = REPO / "godot_project"


def format_violations(project: Path) -> list[str]:
    """Static checks for the two format rules the skills exist to enforce."""
    problems: list[str] = []
    for scene in sorted(project.glob("*.tscn")):
        lines = scene.read_text().splitlines()
        if not lines:
            problems.append(f"{scene.name}: empty file")
            continue
        if "load_steps" in lines[0]:
            problems.append(f"{scene.name}: deprecated load_steps in header")
        if any('uid="uid://' in line for line in lines):
            problems.append(f"{scene.name}: fabricated uid on a resource")
    return problems


def session_cost_usd(client: Anthropic, session_id: str) -> float:
    try:
        usage = getattr(client.beta.sessions.retrieve(session_id), "usage", None)
        amount = getattr(usage, "list_cost", None)
        return int(amount.amount) / 100 if amount else 0.0
    except Exception:
        return 0.0


def run_one(client: Anthropic, brief_path: Path, args, sample: int) -> dict:
    coordinator_id = (REPO / ".coordinator_id").read_text().strip()
    environment_id = (REPO / ".environment_id").read_text().strip()

    swarm.PROJECT_DIR = PROJECT_DIR
    swarm.reset_project()

    session = client.beta.sessions.create(
        agent=coordinator_id,
        environment_id=environment_id,
        title=f"eval — {brief_path.stem} #{sample}",
        budget={"type": "limit",
                "max_list_cost": {"amount": str(int(args.budget_usd * 100)), "currency": "USD"}},
    )
    record: dict = {
        "brief": brief_path.stem,
        "sample": sample,
        "session_id": session.id,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"\n=== {brief_path.stem} #{sample} — {session.id} ===")

    started = time.monotonic()
    swarm.stream_turn(
        client,
        session.id,
        "Build the Godot 4.7 scene described in the brief below. Delegate to the "
        "three builders in a single message so they work in parallel, then have the "
        "Scene Integrator assemble main.tscn. Every file goes to /mnt/session/outputs/. "
        "A local Godot 4.7 engine will verify your output the moment you finish.\n\n"
        "===== LEVEL BRIEF =====\n" + brief_path.read_text(),
    )
    swarm.download_outputs(client, session.id)

    rounds_to_green = None
    for attempt in range(args.max_rounds + 1):
        report = godot_verify.verify(PROJECT_DIR)
        if attempt == 0:
            record["pass_at_round_0"] = report.ok
            record["round_0_findings"] = len(report.findings)
        if report.ok:
            rounds_to_green = attempt
            break
        if attempt == args.max_rounds:
            break
        swarm.stream_turn(client, session.id, godot_verify.format_for_swarm(report))
        swarm.download_outputs(client, session.id)

    record.update(
        passed=rounds_to_green is not None,
        rounds_to_green=rounds_to_green,
        wall_seconds=round(time.monotonic() - started, 1),
        cost_usd=session_cost_usd(client, session.id),
        format_violations=format_violations(PROJECT_DIR),
        files=sorted(p.name for p in PROJECT_DIR.glob("*")
                     if p.name not in godot_verify.PROTECTED_FILES and p.suffix in (".tscn", ".gd")),
    )
    record["format_clean"] = not record["format_violations"]
    print(f"  -> pass@0={record['pass_at_round_0']}  rounds={rounds_to_green}  "
          f"${record['cost_usd']:.2f}  format_clean={record['format_clean']}")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end eval sweep. Spends real money.")
    parser.add_argument("--briefs", nargs="*", type=Path,
                        default=sorted((REPO / "evals" / "briefs").glob("*.md")))
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--budget-usd", type=float, default=8.0)
    parser.add_argument("--yes", action="store_true", help="required: confirms the spend")
    args = parser.parse_args()

    runs = len(args.briefs) * args.samples
    low, high = runs * 2, runs * 4
    print(f"{len(args.briefs)} brief(s) x {args.samples} sample(s) = {runs} runs")
    print(f"Estimated cost: ${low}-{high}.  Estimated wall clock: {runs * 10}-{runs * 20} min.")
    if not args.yes:
        print("\nRefusing to start without --yes.")
        return 2
    if args.samples < 3:
        print("NOTE: fewer than 3 samples per brief — treat the result as anecdote, not signal.")

    godot_verify.find_godot()
    client = Anthropic()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    records: list[dict] = []

    for brief in args.briefs:
        for sample in range(1, args.samples + 1):
            try:
                record = run_one(client, brief, args, sample)
            except BaseException as exc:  # a single bad run must not lose the sweep
                record = {"brief": brief.stem, "sample": sample, "error": repr(exc)}
                print(f"  -> ERRORED: {exc!r}")
            records.append(record)
            with out.open("a") as fh:
                fh.write(json.dumps(record) + "\n")

    ok = [r for r in records if not r.get("error")]
    passed = [r for r in ok if r.get("passed")]
    at_zero = [r for r in ok if r.get("pass_at_round_0")]
    clean = [r for r in ok if r.get("format_clean")]
    cost = sum(r.get("cost_usd", 0) for r in ok)

    print("\n" + "=" * 58)
    print(f"runs            {len(records)}  ({len(records) - len(ok)} errored)")
    if ok:
        print(f"pass@round-0    {len(at_zero)}/{len(ok)}  ({100 * len(at_zero) / len(ok):.0f}%)   <- skill quality")
        print(f"pass eventually {len(passed)}/{len(ok)}  ({100 * len(passed) / len(ok):.0f}%)   <- with repairs")
        print(f"format clean    {len(clean)}/{len(ok)}")
        if passed:
            print(f"mean rounds     {sum(r['rounds_to_green'] for r in passed) / len(passed):.2f}")
            print(f"cost per pass   ${cost / len(passed):.2f}")
    print(f"total spend     ${cost:.2f}")
    print(f"\nresults: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
