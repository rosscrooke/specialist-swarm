# Brief: Gap 2, how the specialists get the deal inputs

This brief covers one issue only: how the RFP and its supporting files reach the specialist agents. It gives the background, the evidence and what "fixed" means. You decide how to write the code.

---

## 1. Background

The repo is a hackathon demo built on **Claude Managed Agents** (multi-agent, beta). A coordinator agent (Opus) reads an inbound RFP, hands out work to four specialist sub-agents in parallel, and combines their answers into a Word proposal.

| Piece | Where |
|---|---|
| Specialists (Pricing, Legal, Technical Fit, Competitive Intel) | `create_specialists.py`, IDs in `.specialist_ids.json` |
| Coordinator, with its roster and system prompt | `create_coordinator.py`, ID in `.coordinator_id` |
| Cloud environment | `setup_environment.py`, ID in `.environment_id` |
| One run (one session) | `run_deal_desk.py`, last ID in `.last_session_id` |
| Input files | `synthetic-data/rfp-acme-corp.md`, `synthetic-data/past-wins.json`, `synthetic-data/product-overview.md` |

The API key is in `.env` (git-ignored), and every script calls `load_dotenv()`. Run scripts with `.venv/bin/python`. The SDK is `anthropic` 2.6.0.

### How multi-agent sessions behave (this is the root of the issue)

- Each agent runs in its own **thread** with its own conversation history.
- All threads share **one container filesystem**.
- A specialist **cannot see the coordinator's conversation**. It only sees the brief the coordinator sends it, plus whatever is on the shared disk.
- Files can be mounted into a session when it is created: upload with the Files API, then pass them as `resources` on `sessions.create`. A file mounted with `mount_path: "/x.md"` appears at `/mnt/session/uploads/x.md`. Mounted files are read-only, and the session works on its own copy (with a different `file_id`).

---

## 2. The problem

`run_deal_desk.py` reads all three input files and pastes their full text into the coordinator's first `user.message` (`load_inputs_as_context()`, then `f"{context}"`). No files are mounted. So at the start of a run, the inputs exist **only in the coordinator's conversation**.

The coordinator's system prompt (`COORDINATOR_SYSTEM` in `create_coordinator.py`, "How to run a deal", step 2) then says each specialist "gets: The full RFP text". That tells the coordinator to paste the whole RFP into four separate briefs. It also never mentions `past-wins.json` (which Pricing needs) or `product-overview.md` (which Technical Fit needs) as files to pass on.

The specialists' own system prompts (`create_specialists.py`) mention `past-wins.json` and `product-overview.md` by name, as if those files were available to them. They aren't, unless the coordinator happens to put them somewhere.

**So whether the specialists get full, accurate inputs depends on the coordinator improvising.** Nothing in the code guarantees it.

---

## 3. Evidence from the first live run

Session `sesn_019XxnnP6aJmpRKv88aUACYP` (6 Nov 2026) finished in about 13 minutes, cost $3.15, and produced `outputs/acme-rfp-response.docx`. The event log shows:

1. **The coordinator retyped all three inputs onto the disk itself**, using `write` tool calls, before delegating:

   | Written to | Characters | Original |
   |---|---|---|
   | `/mnt/deal-desk/acme/rfp.md` | 4,379 | 4,387 |
   | `/mnt/deal-desk/acme/past-wins.json` | 2,925 | 2,927 |
   | `/mnt/deal-desk/acme/product-overview.md` | 3,059 | 3,069 |

   The copies are close to the originals but not exact, and producing them cost about 10,000 characters of Opus output.
2. **It sent four briefs within one second**, roughly 2,300–2,800 characters each. Each brief listed which files to read, which RFP sections to focus on, the questions to answer, an output file path (for example `/mnt/deal-desk/acme/pricing/recommendation.md`) and a word limit.
3. **Each specialist read the files, wrote a report to its own file, and replied** with a summary and the file path.
4. **The coordinator read the reports and resolved a conflict.** Competitive Intel suggested opening at a 35–40% discount; Pricing, which has the playbook, said 22% to open and 28% at most. The coordinator went with Pricing.

The outcome was good, but steps 1 and 2 were the model's own choices and went against the prompt's "full RFP text" instruction. The next run may not repeat them.

To inspect a run's events yourself (read-only), use `client.beta.sessions.events.list(session_id)` and `client.beta.sessions.threads.events.list(thread_id, session_id=...)`. The delegation messages are `agent.thread_message_sent` events on the primary stream.

---

## 4. Target behaviour

Make the good pattern from section 3 guaranteed by the code and the prompt, instead of left to the model:

1. **The code puts the inputs on disk** at session creation, at known, stable paths under `/mnt/session/uploads/`. The coordinator should not have to recreate them.
2. **The coordinator is told where the inputs are**, by path, instead of being handed their full text inline.
3. **The coordinator's prompt sets a delegation contract.** Each brief gives the specialist:
   - the input file paths it needs
   - a narrow set of questions
   - its own output file (somewhere writable, not under `/mnt/session/uploads/`)
   - the reply format: a short summary plus the output file path

   It sends all four briefs in one turn so they run in parallel, and it states plainly that specialists cannot see the coordinator's conversation.
4. **Synthesis reads the specialists' output files.** When specialists disagree, the topic owner wins: Pricing on price, Legal on contract terms.

---

## 5. Constraints and scope

**In scope:** how inputs reach the session, `run_deal_desk.py`, and the delegation and synthesis parts of `COORDINATOR_SYSTEM` (steps 2 and 3, plus the example in "How to talk to specialists").

**Out of scope.** These are separate fixes; leave them alone:
- where the final docx is saved and its name (step 4 of the prompt and item 4 of `user_message`)
- the brand skill
- the Technical Fit skill
- retrying the output download
- the critic stretch script
- the README

**Do not:**
- **Run `create_specialists.py`.** It isn't idempotent: it creates four new agents and orphans the current ones. It's fine to *recommend* changing the specialists' prompts, but don't recreate the agents. If you change a specialist, update it in place with `client.beta.agents.update(id, version=current.version, ...)`, then re-run `create_coordinator.py` so the roster re-pins to the new versions.
- **Run `setup_environment.py`.** The environment already exists.

**You must:**
- **Re-run `create_coordinator.py` after changing the prompt.** It updates the coordinator in place; sessions use the agent's latest version.
- **Keep the inputs read-only, and make sure the specialists know it,** so they write their reports somewhere else.

**Cost:** each `run_deal_desk.py` run takes about 13 minutes and costs about $3. Ask the user before running one.

### API facts to rely on (checked against the installed SDK)

- **Upload:** `client.files.upload(file=..., expires_in_seconds=...)`. `file` accepts a path, bytes, or a `(name, bytes, mime)` tuple, and `expires_in_seconds` is optional (3,600 to 7,776,000). Uploaded originals stay on the account until deleted or expired, so each run adds three.
- **Mount:** `client.beta.sessions.create(agent=..., environment_id=..., title=..., resources=[{"type": "file", "file_id": ..., "mount_path": "/name.ext"}])`.
- **Not yet confirmed live:** which MIME types the Files API accepts for `.md` and `.json`. `text/plain` is the safest choice.

---

## 6. Done when

**After a fresh run:**

| # | Check | How to verify |
|---|---|---|
| 1 | The three inputs are mounted when the session is created | `sessions.retrieve(id).resources` lists three files, or the Console Resources tab does |
| 2 | The coordinator's first message carries paths, not the file contents | The `user.message` text has no RFP body and names `/mnt/session/uploads/...` |
| 3 | The coordinator doesn't recreate the inputs | No `write` tool call on the primary thread writes RFP, past-wins or product-overview content |
| 4 | Every brief points at mounted paths and gives an output file | Each `agent.thread_message_sent` contains `/mnt/session/uploads/` and an output path |
| 5 | Specialists read the real files | Each specialist thread has a `read` (or `bash cat`) on `/mnt/session/uploads/...` |
| 6 | Synthesis uses the reports | The primary thread reads each specialist's output file before building the doc |
| 7 | Nothing else regressed | Four threads spawn in parallel, the session ends `idle` with `end_turn`, and a docx still downloads to `outputs/` |

**Static checks before spending money on a run:**
- `run_deal_desk.py` and `create_coordinator.py` still parse.
- `create_coordinator.py` prints `Coordinator updated` with the same four roster entries.
