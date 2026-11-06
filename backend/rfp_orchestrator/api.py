"""High-level entry point: one call = one RFP run."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from .config import REPO_ROOT, Limits
from .events import EventBus, EventSink, JsonlSink
from .runtime import Orchestration, RunResult
from .workspace import Workspace

DATA_DIR = REPO_ROOT / "synthetic-data"
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("RFP_OUTPUT_ROOT", REPO_ROOT / "outputs"))
DEFAULT_REFERENCES = [DATA_DIR / "past-wins.json", DATA_DIR / "product-overview.md"]

DEFAULT_TASK = """\
A new RFP has arrived: inputs/{rfp_name}.
Reference material in inputs/: {references}.
Run the full bid process and deliver the final proposal response document.
{extra}"""


def new_run_id() -> str:
    return uuid.uuid4().hex[:8]


async def run_rfp(
    rfp_path: Path | None = None,
    *,
    rfp_text: str | None = None,
    rfp_name: str = "rfp.md",
    extra_inputs: list[Path] | None = None,
    instructions: str = "",
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    limits: Limits | None = None,
    sinks: list[EventSink] | None = None,
    run_id: str | None = None,
    client=None,
) -> RunResult:
    """Run the agent team on one RFP (given as a file or as text)."""
    if (rfp_path is None) == (rfp_text is None):
        raise ValueError("Pass exactly one of rfp_path or rfp_text.")
    run_id = run_id or new_run_id()
    extra_inputs = DEFAULT_REFERENCES if extra_inputs is None else extra_inputs

    ws = Workspace.create(output_root / run_id, [*([rfp_path] if rfp_path else []), *extra_inputs])
    if rfp_text is not None:
        (ws.root / "inputs" / rfp_name).write_text(rfp_text, encoding="utf-8")
    else:
        rfp_name = rfp_path.name

    bus = EventBus([JsonlSink(ws.root / "events.jsonl"), *(sinks or [])])
    orch = Orchestration(ws, client=client, limits=limits or Limits.from_env(), bus=bus, run_id=run_id)

    task = DEFAULT_TASK.format(
        rfp_name=rfp_name,
        references=", ".join(p.name for p in extra_inputs) or "none",
        extra=f"\nAdditional instructions: {instructions}" if instructions else "",
    )
    result = await orch.run(task)
    (ws.root / "run-summary.json").write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return result
