"""
Run the local Godot engine against the project the swarm produced and report,
precisely, what is broken.

This is the gate that makes the swarm demo real: a document deliverable can
only be reviewed, but a Godot scene either loads in a real engine or it does
not. The findings this produces are fed straight back to the coordinator.

WHY IT LOOKS LIKE THIS
----------------------
Every design choice below was calibrated empirically against Godot 4.7.2 by
breaking a known-good project four ways and diffing the logs:

    fault                    import   validate   boot    detected by
    GDScript syntax error       0         1        0     validator + log
    bad ext_resource path       0         0        0     LOG ONLY  (stage 1)
    missing sub_resource        0         1        0     validator + log
    runtime null deref          0         0        0     LOG ONLY  (stage 3)

Godot's own exit code was 0 for all four. So:

  * Exit codes are never trusted. Classification is by scraping the merged
    stdout+stderr. (`--check-only` also exits 0 on a file that cannot even be
    opened, and an unrecognised flag hangs the process forever.)
  * All three stages are required — no single stage catches everything.
  * Output is ANSI-coloured even when redirected, so escapes are stripped
    before anything is matched.
  * `--import` runs twice: on a cold tree `class_name` registration is not yet
    populated, which produces spurious "Could not find base class" errors.

Usage:
    python godot_verify.py                     # verify ./godot_project
    python godot_verify.py --project some/dir
    python godot_verify.py --json              # machine-readable only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PROJECT = Path("godot_project")
DEFAULT_REPORT = Path("outputs") / "verify-report.json"

# Files the harness owns. run_scene_build.py refuses to overwrite these with
# anything the swarm produces — they are the contract, not the deliverable.
PROTECTED_FILES = ("project.godot", "_validate.gd")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# ---------------------------------------------------------------------------
# Signatures, all observed in real 4.7.2 output during calibration.
# ---------------------------------------------------------------------------

ERROR_PATTERNS = (
    re.compile(r"^SCRIPT ERROR:\s*(?P<msg>.+)$"),
    re.compile(r"^ERROR:\s*(?P<msg>.+)$"),
    re.compile(r"^USER ERROR:\s*(?P<msg>.+)$"),
)

# Not actionable: symptoms of a failure reported elsewhere, or engine chatter.
# These are dropped only when they are the *whole* line — they never suppress
# a real error that happens to contain the same words.
NOISE_EXACT = (
    "Plugin is not attached to debugger.",
    "Condition \"!int_resources.has(id)\" is true. Returning: ERR_INVALID_PARAMETER",
)
NOISE_SUBSTRINGS = (
    "Parse Error: Busy",              # cold-import artefact, clears on pass 2
    "Could not find base class",      # ditto: class_name not yet registered
    "ObjectDB instances leaked",      # shutdown accounting, not a scene defect
    "Resources still in use at exit",
)

# `          at: _ready (res://player.gd:43)`  → the frame that names user code.
AT_FRAME_RE = re.compile(r"^\s*at:\s*(?P<fn>[^(]+)\((?P<loc>[^)]*)\)\s*$")
# `res://main.tscn:8 - Parse Error: ...`
INLINE_LOC_RE = re.compile(r"(?P<file>res://[^\s:]+):(?P<line>\d+)")
# `... [Resource file res://player.tscn:19]`
RESFILE_LOC_RE = re.compile(r"\[Resource file (?P<file>res://[^\s:]+):(?P<line>\d+)\]")
# A bare path with no line, e.g. `Failed loading resource: res://levl.tscn.`
BARE_PATH_RE = re.compile(r"(?P<file>res://[^\s:'\"]+\.[A-Za-z0-9]+)")
# Godot sometimes repeats the location as a prefix: `res://main.tscn:8 - <msg>`
LOC_PREFIX_RE = re.compile(r"^res://[^\s:]+:\d+\s*-\s*")
# Our own validator's machine-readable channel.
VALIDATE_FAIL_RE = re.compile(r"^VALIDATE_FAIL\|(?P<file>[^|]*)\|(?P<msg>.*)$")
VALIDATE_SUMMARY_RE = re.compile(r"^VALIDATE_SUMMARY\|.*failures=(?P<failures>\d+)\s*$")


@dataclass
class Finding:
    stage: str
    message: str
    file: str | None = None
    line: int | None = None

    def where(self) -> str:
        if self.file and self.line:
            return f"{self.file}:{self.line}"
        return self.file or "(location not reported)"

    def __str__(self) -> str:
        return f"[{self.stage}] {self.where()} — {self.message}"


@dataclass
class StageResult:
    name: str
    command: list[str]
    exit_code: int | None
    timed_out: bool = False
    log: str = ""


@dataclass
class Report:
    ok: bool = False
    project: str = ""
    godot_version: str = ""
    findings: list[Finding] = field(default_factory=list)
    stages: list[StageResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Logs are large and already on disk; keep the JSON readable.
        for stage in d["stages"]:
            stage.pop("log", None)
        return d


# ---------------------------------------------------------------------------


def find_godot() -> str:
    """Locate the engine: explicit env var, then the known install, then PATH."""
    candidates = [
        os.environ.get("GODOT_BIN"),
        "/Users/69784/Downloads/Godot.app/Contents/MacOS/Godot",
        "/Applications/Godot.app/Contents/MacOS/Godot",
        shutil.which("godot"),
        shutil.which("godot4"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise SystemExit(
        "Could not find a Godot binary. Set GODOT_BIN to the executable, e.g.\n"
        "  export GODOT_BIN=/Applications/Godot.app/Contents/MacOS/Godot"
    )


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_stage(name: str, godot: str, args: list[str], timeout: int) -> StageResult:
    """
    Run one Godot invocation. Always bounded by a timeout: macOS has no
    `timeout(1)`, and an unrecognised flag makes Godot hang indefinitely
    rather than erroring, so an unbounded call can wedge the whole pipeline.
    """
    command = [godot, *args]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return StageResult(
            name=name,
            command=command,
            exit_code=proc.returncode,
            log=strip_ansi((proc.stdout or "") + (proc.stderr or "")),
        )
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return StageResult(
            name=name,
            command=command,
            exit_code=None,
            timed_out=True,
            log=strip_ansi(partial),
        )


def _is_noise(message: str) -> bool:
    if message.strip() in NOISE_EXACT:
        return True
    return any(fragment in message for fragment in NOISE_SUBSTRINGS)


def _location_from(message: str) -> tuple[str | None, int | None]:
    """Pull res:// file and line out of the message body itself."""
    for pattern in (RESFILE_LOC_RE, INLINE_LOC_RE):
        match = pattern.search(message)
        if match:
            return match.group("file"), int(match.group("line"))
    # No line number available, but naming the file is still far more useful
    # to the agent that has to fix it than "location not reported".
    bare = BARE_PATH_RE.search(message)
    if bare:
        return bare.group("file"), None
    return None, None


def classify(stage: StageResult) -> list[Finding]:
    """
    Turn one stage's log into findings.

    Godot prints an error as a message line optionally followed by an indented
    `at: <fn> (<location>)` frame. The message carries the *what*; the frame
    carries the *where* — but only when it names a res:// path. Frames pointing
    into Godot's own C++ (`gdscript.cpp:1139`) are engine internals and are of
    no use to the agent that has to fix the file, so they are discarded.
    """
    findings: list[Finding] = []
    lines = stage.log.splitlines()

    if stage.timed_out:
        findings.append(
            Finding(stage=stage.name, message="Godot did not exit within the timeout — likely a hang, not a scene defect.")
        )

    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip()

        validate_fail = VALIDATE_FAIL_RE.match(line)
        if validate_fail:
            findings.append(
                Finding(
                    stage=stage.name,
                    message=validate_fail.group("msg").strip(),
                    file=validate_fail.group("file").strip() or None,
                )
            )
            continue

        for pattern in ERROR_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            message = match.group("msg").strip()
            if _is_noise(message):
                break

            file_path, line_no = _location_from(message)
            if file_path is None:
                # Look ahead for the `at:` frame, but only take it if it names
                # a res:// path — a C++ frame tells the agent nothing.
                for lookahead in lines[index + 1 : index + 3]:
                    frame = AT_FRAME_RE.match(lookahead)
                    if not frame:
                        continue
                    loc_match = INLINE_LOC_RE.search(frame.group("loc"))
                    if loc_match:
                        file_path = loc_match.group("file")
                        line_no = int(loc_match.group("line"))
                    break

            findings.append(
                Finding(
                    stage=stage.name,
                    # The location is rendered separately, so drop it when
                    # Godot has already repeated it as a message prefix.
                    message=LOC_PREFIX_RE.sub("", message),
                    file=file_path,
                    line=line_no,
                )
            )
            break

    return findings


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """The same defect surfaces in several stages; report each one once."""
    seen: set[tuple] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (finding.message, finding.file, finding.line)
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


def verify(project: Path, timeout: int = 300, frames: int = 120) -> Report:
    godot = find_godot()
    project = project.resolve()
    if not (project / "project.godot").is_file():
        raise SystemExit(f"No project.godot in {project} — is that the right directory?")

    version = subprocess.run(
        [godot, "--version"], capture_output=True, text=True, timeout=60
    ).stdout.strip()

    report = Report(project=str(project), godot_version=version)
    base = ["--headless", "--path", str(project)]

    # Stage 1 — import. Twice: pass 1 on a cold tree reports phantom errors
    # because class_name registration has not happened yet. Only pass 2 counts.
    report.stages.append(run_stage("import (cold)", godot, [*base, "--import"], timeout))
    import_pass = run_stage("import", godot, [*base, "--import"], timeout)
    report.stages.append(import_pass)

    # Stage 2 — our own validator, the one exit code we can trust.
    validate = run_stage(
        "validate", godot, [*base, "--script", "res://_validate.gd"], timeout
    )
    report.stages.append(validate)

    # Stage 3 — actually boot the main scene. Headless swaps only the display
    # and audio drivers, so _ready/_physics_process really do run.
    report.stages.append(
        run_stage(
            "boot",
            godot,
            [*base, "--quit-after", str(frames), "--fixed-fps", "60"],
            timeout,
        )
    )

    findings: list[Finding] = []
    for stage in report.stages:
        if stage.name == "import (cold)":
            continue  # noisy by design; pass 2 is the authoritative one
        findings.extend(classify(stage))

    report.findings = _dedupe(findings)
    report.ok = not report.findings and validate.exit_code == 0
    return report


def format_for_swarm(report: Report) -> str:
    """Render findings as the message sent back to the coordinator."""
    if report.ok:
        return "Godot verification passed: the project imports, every scene instantiates, and the main scene boots with no errors."

    lines = [
        "Godot verification FAILED. This is real output from Godot "
        f"{report.godot_version} running locally against the files you produced.",
        "",
        "Findings:",
    ]
    for i, finding in enumerate(report.findings, 1):
        lines.append(f"{i}. [{finding.stage}] {finding.where()}")
        lines.append(f"   {finding.message}")
    lines += [
        "",
        "Fix ONLY these problems. Rewrite the affected files in full to "
        "/mnt/session/outputs/ using the same filenames. Do not rename files, "
        "do not restructure the scene tree, and do not write project.godot or "
        "_validate.gd — those are owned by the harness.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--timeout", type=int, default=300, help="per-stage seconds")
    parser.add_argument("--frames", type=int, default=120, help="frames to boot for")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()

    report = verify(args.project, timeout=args.timeout, frames=args.frames)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.to_dict(), indent=2))

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.ok else 1

    print(f"Godot   {report.godot_version}")
    print(f"Project {report.project}")
    for stage in report.stages:
        status = "timeout" if stage.timed_out else f"exit {stage.exit_code}"
        print(f"  stage {stage.name:<14} {status}")
    print()
    if report.ok:
        print("PASS — project imports, instantiates, and boots cleanly.")
    else:
        print(f"FAIL — {len(report.findings)} finding(s):\n")
        for finding in report.findings:
            print(f"  {finding}")
    print(f"\nReport written to {args.report}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
