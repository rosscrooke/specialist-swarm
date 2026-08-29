"""
Tier 1 eval — regression test for the verification harness itself.

Free, offline, ~3 minutes. No API key, no model calls.

WHY THIS EXISTS
---------------
godot_verify.py is the grader for everything else. If it silently stops
detecting a fault class, every downstream eval turns green and lies to you —
the worst possible failure, because it looks like success.

So this reproduces, as an executable test, the calibration that produced the
harness in the first place: take a known-good scene, inject each fault class,
and assert the harness still catches it.

The four faults are not arbitrary. They are one per detection path:

    fault                    caught by
    GDScript syntax error    validator exit code + log scrape
    bad ext_resource path    LOG SCRAPE ONLY  (import stage)
    missing sub_resource     validator exit code + log scrape
    runtime null deref       LOG SCRAPE ONLY  (boot stage)

Two of the four are visible to exactly one stage, which is why all three
stages exist. Godot's own exit code is 0 for all four.

Usage:
    python evals/harness_regression.py
    python evals/harness_regression.py --keep    # leave the temp project on disk
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import godot_verify  # noqa: E402

REFERENCE = REPO / "reference-scene"
HARNESS_FILES = REPO / "godot_project"


@dataclass
class Case:
    name: str
    target: str | None           # file to corrupt; None = leave clean
    find: str = ""
    replace: str = ""
    append: str = ""
    # Expectations
    expect_pass: bool = False
    expect_file: str = ""        # a finding must name this res:// path
    expect_message: str = ""     # ...and its message must contain this
    expect_stage: str = ""       # ...from this stage (substring match)


CASES = [
    Case(
        name="clean scene",
        target=None,
        expect_pass=True,
    ),
    Case(
        name="GDScript syntax error",
        target="player.gd",
        find='var direction: float = Input.get_axis("move_left", "move_right")',
        replace='var direction: float = Input.get_axis("move_left" "move_right"',
        expect_file="res://player.gd",
        expect_message="Parse Error",
        expect_stage="import",
    ),
    Case(
        name="ext_resource points at a missing file",
        target="main.tscn",
        find='path="res://level.tscn"',
        replace='path="res://levl.tscn"',
        expect_file="res://levl.tscn",
        expect_message="Cannot open file",
        expect_stage="import",
    ),
    Case(
        name="sub_resource id never declared",
        target="player.tscn",
        find='shape = SubResource("RectangleShape2D_body")',
        replace='shape = SubResource("RectangleShape2D_nope")',
        expect_file="res://player.tscn",
        expect_message="",
        expect_stage="",
    ),
    Case(
        name="runtime null dereference in _ready",
        target="player.gd",
        append=(
            "\n\nfunc _ready() -> void:\n"
            '\tvar missing: Node = get_node_or_null("DoesNotExist")\n'
            "\tmissing.set_process(false)\n"
        ),
        expect_file="res://player.gd",
        expect_message="null value",
        expect_stage="boot",
    ),
]


def build_project(root: Path) -> None:
    """A fresh project: harness-owned files plus the known-good reference scene."""
    root.mkdir(parents=True, exist_ok=True)
    for name in godot_verify.PROTECTED_FILES:
        shutil.copy2(HARNESS_FILES / name, root / name)
    for src in list(REFERENCE.glob("*.tscn")) + list(REFERENCE.glob("*.gd")):
        shutil.copy2(src, root / src.name)


def apply_fault(root: Path, case: Case) -> None:
    if case.target is None:
        return
    path = root / case.target
    text = path.read_text()
    if case.find:
        if case.find not in text:
            raise SystemExit(
                f"FIXTURE DRIFT: {case.name!r} expected to find this in "
                f"{case.target}, and did not:\n  {case.find}\n"
                "The reference scene changed — update evals/harness_regression.py."
            )
        text = text.replace(case.find, case.replace)
    text += case.append
    path.write_text(text)


def check(case: Case, report: godot_verify.Report) -> tuple[bool, str]:
    if case.expect_pass:
        if report.ok:
            return True, "no findings, as expected"
        return False, f"expected a clean pass, got {len(report.findings)} finding(s)"

    if report.ok:
        return False, "harness reported PASS on a deliberately broken project"

    for finding in report.findings:
        if case.expect_file and finding.file != case.expect_file:
            continue
        if case.expect_message and case.expect_message not in finding.message:
            continue
        if case.expect_stage and case.expect_stage not in finding.stage:
            continue
        located = f" ({finding.where()})" if finding.line else ""
        return True, f"caught in [{finding.stage}]{located}"

    got = "; ".join(f"[{f.stage}] {f.where()} {f.message[:60]}" for f in report.findings[:3])
    return False, f"detected a problem but not the expected one — got: {got}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Regression-test the Godot verification harness.")
    parser.add_argument("--keep", action="store_true", help="leave the temp project on disk")
    args = parser.parse_args()

    godot_verify.find_godot()  # fail fast with a clear message if absent

    workdir = Path(tempfile.mkdtemp(prefix="stagehands-eval-"))
    results: list[tuple[str, bool, str]] = []

    print(f"Harness regression — {len(CASES)} cases\nworkdir: {workdir}\n")
    try:
        for case in CASES:
            root = workdir / case.name.replace(" ", "_")
            build_project(root)
            apply_fault(root, case)
            report = godot_verify.verify(root)
            ok, detail = check(case, report)
            results.append((case.name, ok, detail))
            print(f"  {'PASS' if ok else 'FAIL'}  {case.name:38s} {detail}")
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)

    failed = [name for name, ok, _ in results if not ok]
    print()
    if failed:
        print(f"{len(failed)} of {len(results)} cases FAILED: {', '.join(failed)}")
        print("The grader is not trustworthy until these pass.")
        return 1
    print(f"All {len(results)} cases passed — the harness still detects every fault class.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
