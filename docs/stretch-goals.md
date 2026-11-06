# Stretch Goals — Option 3

Pick at least one. The big-ticket ones (S1, S2, S5) are the ones that make the demo really sing.

---

## Tier 1 — Make it your own

### S1. Codify YOUR firm's voice as a Skill
Every services firm has a distinctive voice. Create `skills/your-firm-voice/SKILL.md` codifying yours. Some flavors to start from:

- **Transformation-led voice**: confident, business-case-anchored, lots of "What this means for you"
- **Risk-anchored voice**: conservative, peer-benchmarked, lots of "industry leaders are…"
- **Delivery-anchored voice**: "we'll make it real" framing, lots of implementation specifics

Add the skill to the coordinator's skill list. Re-run the deal. The output should now sound like *your* firm wrote it.

**Why this lands:** Skills are the easiest knob to turn for partner-specific customisation. Each partner in the room will want their own. This is the demo that gets them to lean forward.

---

## Tier 2 — Make the swarm smarter

### S2. The Critic sub-agent
Run `uv run python -m app.stretch_critic` in `backend/`. This adds a fifth agent whose only job is to push back on the coordinator's draft before it ships. The coordinator now MUST consult the critic before producing the final doc. Watch what happens to quality.

**Why this lands:** Demonstrates an adversarial review pattern inside the swarm. Maps directly to how real services firms run a partner review.

### S3. Memory across deals
Wire up the [Memory tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) to the coordinator. Run two consecutive deals from different fictional customers. The second deal should reference what the coordinator learned from the first ("we typically win these on TCO, not headline price — Acme last quarter…").

**Why this lands:** Now the swarm gets better over time, not just on this one deal.

### S4. Parallelism: explicitly fan out
Modify the coordinator's prompt to instruct: "delegate to all four specialists in a SINGLE message — do not wait between them." Then watch the events stream — all four threads should spawn within seconds of each other.

This is the visible parallelism story.

**Why this lands:** This is the visual that lands the architecture pitch. "Four specialists, parallel, one synthesis."

---

## Tier 3 — Wire the system to the real world

### S5. Add a synthetic CRM MCP
Build a tiny MCP server that exposes "past wins" as a queryable API instead of a JSON file. Wire it to the Pricing Specialist. Now the specialist queries a real-looking system instead of reading a static file.

**Why this lands:** This is the architecture they'll deploy at clients. CRM, ITSM, PSA — every one of these gets wrapped in an MCP and consumed by specialists.

### S6. Add a Slack notification step
Add a fifth specialist whose only job is to post the deal status to a Slack channel as the swarm progresses ("Pricing in — Legal flagged 3 issues — coordinator finalising"). Lets you watch the swarm work from a Slack channel.

**Why this lands:** Bridges the swarm into a real workflow surface.

### S7. Output a real .pptx instead of .docx
Add the [pptx skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/quickstart) to the coordinator. Have the coordinator produce a 5-slide pitch deck version of the proposal in addition to the docx.

**Why this lands:** Now you're producing both a written proposal AND an executive deck from one swarm. That's the actual deliverable for a real deal.

---

## Tier 4 — For the showoffs

### S8. The escalation pattern
Add a "Strategic Pricing" sub-agent that uses claude-opus-4-7. The Pricing Specialist (which uses Sonnet) should delegate to Strategic Pricing only when the deal exceeds $500K. Demonstrates the "escalation" multi-agent pattern from the docs.

### S9. The voting pattern
For the contentious calls (e.g., "should we accept the MFN clause?"), spawn three parallel copies of the Legal Reviewer, each with a slightly different system prompt (conservative / balanced / aggressive). Have the coordinator synthesise their three opinions.

**Why this lands:** Shows how to use multi-agent for *judgment* problems, not just task parallelism.

### S10. The recursion pattern
After producing the docx, have the coordinator generate a question for itself: "What's the riskiest assumption in this proposal?" Spawn a new session to investigate that question. Loop until the coordinator says "stop."

This is genuine autonomous agentic work. Don't run it in a paid workspace without spend caps.

---

## Picking guidance

| If your team has 20 minutes | Pick |
| --- | --- |
| Best visual demo punchline | S2 (Critic) or S4 (explicit parallelism) |
| Best for selling to your firm internally | S1 (your firm's voice as a Skill) |
| Best architecture demo for client CIO | S5 (synthetic CRM MCP) |
| Best "next quarter we should build this" outcome | S6 + S7 (Slack + pptx output) |
