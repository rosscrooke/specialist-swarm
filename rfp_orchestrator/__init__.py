"""Hierarchical multi-agent RFP orchestration on the Claude Messages API.

Quick use from other code (e.g. the frontend backend):

    from rfp_orchestrator import run_rfp
    result = await run_rfp(rfp_path, extra_inputs=[...], sinks=[my_async_sink])
"""

from .api import run_rfp
from .config import Limits
from .events import ConsoleSink, Event, EventBus, JsonlSink
from .runtime import Orchestration, RunResult
from .workspace import Workspace

__all__ = [
    "run_rfp",
    "Limits",
    "Event",
    "EventBus",
    "ConsoleSink",
    "JsonlSink",
    "Orchestration",
    "RunResult",
    "Workspace",
]
