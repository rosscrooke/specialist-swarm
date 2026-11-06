"""High-level entry point: one call = one RFP run."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path

from .config import REPO_ROOT, Limits
from .events import EventBus, EventSink, JsonlSink
from .runtime import Orchestration, RunResult
from .workspace import Workspace

DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs"

DEFAULT_TASK = """\
A new RFP has arrived: inputs/{rfp_name}.
Reference material in inputs/: {references}.
Run the full bid process and deliver the final proposal response document.
{extra}"""


async def run_rfp(
    rfp_path: Path,
    *,
    extra_inputs: list[Path] | None = None,
    instructions: str = "",
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    limits: Limits | None = None,
    sinks: list[EventSink] | None = None,
    run_id: str | None = None,
    client=None,
) -> RunResult:
    run_id = run_id or uuid.uuid4().hex[:8]
    extra_inputs = extra_inputs or []
    ws = Workspace.create(output_root / run_id, [rfp_path, *extra_inputs])

    bus = EventBus([JsonlSink(ws.root / "events.jsonl"), *(sinks or [])])
    orch = Orchestration(ws, client=client, limits=limits or Limits.from_env(), bus=bus, run_id=run_id)

    task = DEFAULT_TASK.format(
        rfp_name=rfp_path.name,
        references=", ".join(p.name for p in extra_inputs) or "none",
        extra=f"\nAdditional instructions: {instructions}" if instructions else "",
    )
    result = await orch.run(task)
    (ws.root / "run-summary.json").write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return result
