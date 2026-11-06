"""Hierarchical agent runtime on the Claude Messages API.

    Orchestrator (depth 0)  --delegate-->  Specialists (depth 1)  --delegate-->  Helpers (depth 2)
       unlimited children                    max 3 children each                 no delegation

Each agent is its own manual tool-use loop with its own context window.
`delegate` is a client-side tool: when an agent calls it, the runtime starts a
child agent loop and returns the child's final report as the tool result.
Several `delegate` calls in one assistant turn run concurrently.

All limits (depth, children per agent, total agents, concurrency, turns) are
enforced here in code - not just requested in prompts.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .agents import ALL_AGENTS, ORCHESTRATOR, AgentSpec
from .config import FALLBACK_BETA, FALLBACK_MODELS, Limits
from .events import Event, EventBus
from .output import write_proposal
from .workspace import Workspace, WorkspaceError

# --------------------------------------------------------------------------- #
# Tool input models (validated in code: eager input streaming skips API-side
# validation, so every tool input is checked here before it runs).
# --------------------------------------------------------------------------- #


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListFilesInput(_Strict):
    pass


class ReadFileInput(_Strict):
    path: str = Field(min_length=1)


class WriteWorkFileInput(_Strict):
    path: str = Field(min_length=1)
    content: str


class DelegateInput(_Strict):
    agent: str
    task: str = Field(min_length=20)


class WriteFinalInput(_Strict):
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=50)


TOOL_MODELS: dict[str, type[BaseModel]] = {
    "list_files": ListFilesInput,
    "read_file": ReadFileInput,
    "write_work_file": WriteWorkFileInput,
    "delegate": DelegateInput,
    "write_final_proposal": WriteFinalInput,
}


# --------------------------------------------------------------------------- #
# Bookkeeping
# --------------------------------------------------------------------------- #


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def add(self, u: Any) -> None:
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.cache_read_input_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
        self.cache_creation_input_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0

    def merge(self, other: "Usage") -> None:
        for k in vars(self):
            setattr(self, k, getattr(self, k) + getattr(other, k))

    def as_dict(self) -> dict[str, int]:
        return dict(vars(self))


@dataclass
class AgentNode:
    id: str
    spec: AgentSpec
    depth: int
    parent_id: str | None
    task: str
    children: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class AgentResult:
    agent_id: str
    agent_key: str
    ok: bool
    text: str
    turns: int
    usage: Usage
    error: str | None = None


@dataclass
class RunResult:
    run_id: str
    ok: bool
    final_text: str
    deliverables: list[str]
    agents: list[dict[str, Any]]
    usage_by_model: dict[str, dict[str, int]]
    duration_s: float


class DelegationRejected(Exception):
    pass


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #


class Orchestration:
    def __init__(
        self,
        workspace: Workspace,
        *,
        client: AsyncAnthropic | None = None,
        limits: Limits | None = None,
        bus: EventBus | None = None,
        run_id: str | None = None,
        use_fallbacks: bool = True,
    ) -> None:
        self.client = client or AsyncAnthropic(max_retries=5)
        self.ws = workspace
        self.limits = limits or Limits()
        self.bus = bus or EventBus()
        self.run_id = run_id or uuid.uuid4().hex[:8]
        self.use_fallbacks = use_fallbacks
        self._sem = asyncio.Semaphore(self.limits.max_concurrent_requests)
        self._nodes: dict[str, AgentNode] = {}
        self._deliverables: list[str] = []
        self._usage_by_model: dict[str, Usage] = {}

    # ---- public API ------------------------------------------------------ #
    async def run(self, task: str) -> RunResult:
        t0 = time.monotonic()
        await self._emit("run_started", data={"task": task})
        node = self._spawn(ORCHESTRATOR, task, depth=0, parent=None)
        result = await self._run_agent(node)
        summary = {
            "ok": result.ok,
            "agents": len(self._nodes),
            "deliverables": self._deliverables,
        }
        await self._emit("run_finished", data={"summary": summary})
        return RunResult(
            run_id=self.run_id,
            ok=result.ok,
            final_text=result.text,
            deliverables=list(self._deliverables),
            agents=[
                {
                    "id": n.id,
                    "key": n.spec.key,
                    "name": n.spec.name,
                    "model": n.spec.model,
                    "depth": n.depth,
                    "parent_id": n.parent_id,
                    "children": n.children,
                    "usage": n.usage.as_dict(),
                }
                for n in self._nodes.values()
            ],
            usage_by_model={m: u.as_dict() for m, u in self._usage_by_model.items()},
            duration_s=time.monotonic() - t0,
        )

    # ---- tree management ------------------------------------------------- #
    def _spawn(self, spec: AgentSpec, task: str, depth: int, parent: AgentNode | None) -> AgentNode:
        """Reserve a slot in the tree. Synchronous => atomic under asyncio."""
        if len(self._nodes) >= self.limits.max_total_agents:
            raise DelegationRejected(
                f"Run-wide limit of {self.limits.max_total_agents} agents reached. Do the work yourself."
            )
        if parent is not None:
            if spec.key not in parent.spec.can_delegate_to:
                allowed = ", ".join(parent.spec.can_delegate_to) or "none"
                raise DelegationRejected(f"'{spec.key}' is not in your roster. Allowed: {allowed}.")
            if depth > self.limits.max_depth:
                raise DelegationRejected("Maximum delegation depth reached. Do the work yourself.")
            cap = self.limits.max_children(parent.depth)
            if cap is not None and len(parent.children) >= cap:
                raise DelegationRejected(
                    f"You have used all {cap} of your delegations. Do the remaining work yourself."
                )
        node = AgentNode(
            id=f"{spec.key[:3]}-{uuid.uuid4().hex[:5]}",
            spec=spec,
            depth=depth,
            parent_id=parent.id if parent else None,
            task=task,
        )
        self._nodes[node.id] = node
        if parent is not None:
            parent.children.append(node.id)
        return node

    def _can_delegate(self, node: AgentNode) -> bool:
        return bool(node.spec.can_delegate_to) and self.limits.max_children(node.depth) != 0

    # ---- tool definitions ------------------------------------------------ #
    def _tools_for(self, node: AgentNode) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = [
            {
                "name": "list_files",
                "description": "List all files in the shared workspace (inputs/, work/, final/).",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "read_file",
                "description": "Read a text file from the workspace, e.g. 'inputs/rfp.md' or 'work/requirements.md'.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Workspace-relative path."}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "write_work_file",
                "description": (
                    "Write (overwrite) a markdown/text file under work/ to share an artifact with other "
                    "agents. Returns the path."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path under work/, e.g. 'work/pricing.md'."},
                        "content": {"type": "string", "description": "Full file content."},
                    },
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
            },
        ]
        if self._can_delegate(node):
            roster = [ALL_AGENTS[k] for k in node.spec.can_delegate_to]
            roster_text = "\n".join(f"- {a.key}: {a.description}" for a in roster)
            cap = self.limits.max_children(node.depth)
            cap_text = "no fixed limit" if cap is None else f"at most {cap} delegations in total"
            tools.append(
                {
                    "name": "delegate",
                    "description": (
                        "Delegate a self-contained task to a team member and receive their final report. "
                        "The member sees none of your conversation - include goal, file paths, constraints "
                        f"and report format. Multiple calls in one turn run in parallel ({cap_text}).\n"
                        f"Team members:\n{roster_text}"
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "agent": {"type": "string", "enum": [a.key for a in roster]},
                            "task": {"type": "string", "description": "Complete, self-contained brief."},
                        },
                        "required": ["agent", "task"],
                        "additionalProperties": False,
                    },
                }
            )
        if node.spec.can_write_final:
            tools.append(
                {
                    "name": "write_final_proposal",
                    "description": (
                        "Write the final proposal deliverable (markdown -> .md and branded .docx in final/). "
                        "Call once, with the complete document."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "markdown": {"type": "string", "description": "Complete proposal in markdown."},
                        },
                        "required": ["title", "markdown"],
                        "additionalProperties": False,
                    },
                }
            )
        # Large inputs (file bodies, documents) stream as generated.
        for t in tools:
            t["eager_input_streaming"] = True
        return tools

    # ---- model call ------------------------------------------------------ #
    async def _call_model(self, node: AgentNode, system: str, messages: list, tools: list) -> Any:
        spec = node.spec
        kwargs: dict[str, Any] = dict(
            model=spec.model,
            max_tokens=self.limits.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": spec.effort},
            cache_control={"type": "ephemeral"},  # auto-cache the growing prefix
        )
        if self.use_fallbacks and spec.model in FALLBACK_MODELS:
            kwargs["fallbacks"] = "default"
            kwargs["betas"] = [FALLBACK_BETA]

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                async with self._sem:
                    async with self.client.beta.messages.stream(**kwargs) as stream:
                        return await stream.get_final_message()
            except ValueError as exc:
                # Unparseable streamed tool-input JSON (eager input streaming): retry the turn.
                last_exc = exc
                await asyncio.sleep(1 + attempt)
        raise RuntimeError(f"Model call failed after retries: {last_exc!r}")

    # ---- agent loop ------------------------------------------------------ #
    async def _run_agent(self, node: AgentNode) -> AgentResult:
        spec = node.spec
        t0 = time.monotonic()
        system = spec.full_system_prompt(self.limits.max_children(node.depth) if self._can_delegate(node) else 0)
        tools = self._tools_for(node)
        messages: list[dict[str, Any]] = [{"role": "user", "content": node.task}]
        await self._emit(
            "agent_started", node, {"model": spec.model, "task": node.task, "tools": [t["name"] for t in tools]}
        )

        last_text = ""
        turns = 0
        try:
            while turns < self.limits.max_turns_per_agent:
                turns += 1
                response = await self._call_model(node, system, messages, tools)
                node.usage.add(response.usage)
                self._usage_by_model.setdefault(response.model, Usage()).add(response.usage)
                # Append-only history: the full content (incl. thinking/fallback blocks) goes back unchanged.
                messages.append({"role": "assistant", "content": response.content})

                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if text:
                    last_text = text
                    await self._emit("agent_text", node, {"text": text})

                if response.stop_reason == "refusal":
                    details = getattr(response, "stop_details", None)
                    raise RuntimeError(f"Model refused (category={getattr(details, 'category', None)})")
                if response.stop_reason == "pause_turn":
                    continue

                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason == "max_tokens":
                    if not tool_uses:
                        last_text += "\n\n[Note: output was truncated at max_tokens.]"
                        break
                    # A truncated tool input must not run - ask the model to retry smaller.
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": b.id,
                                    "is_error": True,
                                    "content": "Output limit hit while writing this tool call; it was not "
                                    "executed. Retry with a shorter input (split large files).",
                                }
                                for b in tool_uses
                            ],
                        }
                    )
                    continue
                if not tool_uses:
                    break  # end_turn: done

                results = await asyncio.gather(*(self._execute_tool(node, b) for b in tool_uses))
                messages.append({"role": "user", "content": list(results)})
            else:
                last_text += f"\n\n[Note: stopped after {self.limits.max_turns_per_agent} turns.]"

            result = AgentResult(node.id, spec.key, True, last_text or "(no report)", turns, node.usage)
        except (anthropic.APIError, RuntimeError) as exc:
            await self._emit("agent_error", node, {"error": str(exc)})
            result = AgentResult(node.id, spec.key, False, last_text, turns, node.usage, error=str(exc))

        await self._emit(
            "agent_finished",
            node,
            {
                "ok": result.ok,
                "turns": turns,
                "duration_s": time.monotonic() - t0,
                "usage": node.usage.as_dict(),
                "report": result.text,
            },
        )
        return result

    # ---- tool execution -------------------------------------------------- #
    async def _execute_tool(self, node: AgentNode, block: Any) -> dict[str, Any]:
        def result(content: str, is_error: bool = False) -> dict[str, Any]:
            r: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id, "content": content}
            if is_error:
                r["is_error"] = True
            return r

        model_cls = TOOL_MODELS.get(block.name)
        if model_cls is None:
            return result(f"Unknown tool '{block.name}'.", True)
        try:
            args = model_cls.model_validate(block.input)
        except ValidationError as exc:
            return result(f"Invalid input for {block.name}: {exc.errors(include_url=False)}. Raw: {block.input!r}", True)

        await self._emit("agent_tool_call", node, {"tool": block.name, "input": _preview_input(block.input)})
        try:
            if isinstance(args, ListFilesInput):
                return result(self.ws.list_files())
            if isinstance(args, ReadFileInput):
                return result(self.ws.read_file(args.path))
            if isinstance(args, WriteWorkFileInput):
                path = self.ws.write_work_file(args.path, args.content)
                rel = str(path.relative_to(self.ws.root))
                await self._emit("file_written", node, {"path": rel})
                return result(f"Saved {rel} ({len(args.content)} chars).")
            if isinstance(args, WriteFinalInput):
                if not node.spec.can_write_final:
                    return result("You are not allowed to write the final deliverable.", True)
                paths = write_proposal(self.ws.root / "final", args.title, args.markdown)
                rels = [str(p.relative_to(self.ws.root)) for p in paths]
                self._deliverables.extend(str(p) for p in paths)
                for rel in rels:
                    await self._emit("file_written", node, {"path": rel})
                return result(f"Deliverable written: {', '.join(rels)}")
            if isinstance(args, DelegateInput):
                return await self._delegate(node, args, result)
        except WorkspaceError as exc:
            return result(str(exc), True)
        return result(f"Tool '{block.name}' not available.", True)

    async def _delegate(self, parent: AgentNode, args: DelegateInput, result) -> dict[str, Any]:
        if not self._can_delegate(parent):
            return result("You cannot delegate. Do the work yourself.", True)
        spec = ALL_AGENTS.get(args.agent)
        if spec is None:
            return result(f"Unknown agent '{args.agent}'.", True)
        try:
            child = self._spawn(spec, args.task, depth=parent.depth + 1, parent=parent)
        except DelegationRejected as exc:
            await self._emit("delegation_rejected", parent, {"agent": args.agent, "reason": str(exc)})
            return result(str(exc), True)

        child_result = await self._run_agent(child)
        cap = self.limits.max_children(parent.depth)
        remaining = "unlimited" if cap is None else str(cap - len(parent.children))
        header = f"[Report from {spec.name} ({child.id}) | delegations left: {remaining}]\n"
        if not child_result.ok:
            return result(
                header + f"The agent failed: {child_result.error}. Partial output:\n{child_result.text}", True
            )
        return result(header + child_result.text)

    # ---- events ---------------------------------------------------------- #
    async def _emit(self, type_: str, node: AgentNode | None = None, data: dict | None = None) -> None:
        await self.bus.emit(
            Event(
                type=type_,  # type: ignore[arg-type]
                run_id=self.run_id,
                agent_id=node.id if node else None,
                agent_name=node.spec.name if node else None,
                parent_id=node.parent_id if node else None,
                depth=node.depth if node else None,
                data=data or {},
            )
        )


def _preview_input(inp: Any, n: int = 300) -> Any:
    """Shorten long string values (file bodies) for the event stream."""
    if isinstance(inp, dict):
        return {k: (v[:n] + "…" if isinstance(v, str) and len(v) > n else v) for k, v in inp.items()}
    return inp
