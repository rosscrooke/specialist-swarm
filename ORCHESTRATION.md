# RFP Agent Orchestration (Option B – Messages API)

Hierarchical multi-agent team in plain Python on the Claude Messages API.
Limits are **enforced in code**, not only requested in prompts.

```
Bid Lead (Opus 5.5, depth 0)            → beliebig viele Spezialisten (parallel)
 ├─ Requirements Analyst (Sonnet 5.5)   → max. 3 Helper
 ├─ Technical Fit / Pricing / Legal / Competitive / Bid Reviewer
 │     └─ Document Analyst | Section Writer | Fact Checker (Haiku 5.5, depth 2, keine Delegation)
```

## Quickstart

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # or put it in .env
.venv/bin/python -m rfp_orchestrator --show-text
.venv/bin/python -m pytest tests -q        # offline tests, no API calls
```

Output per run: `outputs/<run_id>/` with `inputs/`, `work/` (shared scratch),
`final/proposal-response.{md,docx}`, `events.jsonl`, `run-summary.json`.

## How it works

- Each agent = its own tool-use loop + its own context window (`runtime.py`).
- `delegate(agent, task)` is a client-side tool. The runtime spawns the child
  loop and returns its final report as the tool result. Multiple `delegate`
  calls in one turn run concurrently (`asyncio.gather`).
- Agents share files via the workspace (`inputs/` read-only, `work/` shared).
- Enforced limits (`config.Limits`, overridable via env):

| Limit | Default | Env |
|---|---|---|
| Max depth | 2 | `RFP_MAX_DEPTH` |
| Children of orchestrator | unlimited | `RFP_MAX_CHILDREN_ORCHESTRATOR` |
| Children per specialist | 3 | `RFP_MAX_CHILDREN_SPECIALIST` |
| Agents per run | 40 | `RFP_MAX_TOTAL_AGENTS` |
| Parallel API requests | 8 | `RFP_MAX_CONCURRENT_REQUESTS` |

- Models via `RFP_MODEL_ORCHESTRATOR / _SPECIALIST / _HELPER`.
- Opus/Sonnet requests use server-side refusal fallbacks (`fallbacks: "default"`,
  beta `server-side-fallback-2026-07-01`); disable with `Orchestration(use_fallbacks=False)`.
- Prompt caching (auto), adaptive thinking, per-agent effort, streaming.

## Integration (frontend / deployment)

```python
from rfp_orchestrator import run_rfp

async def sse_sink(event):          # Event -> event.to_json()
    await queue.put(event.to_json())

result = await run_rfp(rfp_path, extra_inputs=[...], sinks=[sse_sink])
```

Event types: `run_started, agent_started, agent_text, agent_tool_call,
delegation_rejected, file_written, agent_finished, agent_error, run_finished`.
Each event carries `agent_id`, `parent_id`, `depth` → the frontend can draw the tree live.

## Extending

Add an `AgentSpec` to `SPECIALISTS` or `HELPERS` in `agents.py`. The
`description` is what the parent reads when choosing whom to delegate to.
Skills in `skills/<name>/SKILL.md` are injected via `skills=("name",)`.
