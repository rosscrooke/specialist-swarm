"""Agent roster: orchestrator, specialists (depth 1), helpers (depth 2).

To add a new specialist or helper, add an `AgentSpec` to SPECIALISTS / HELPERS.
`description` is what the parent agent reads when deciding whom to delegate to,
so write it for that reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import MODEL_HELPER, MODEL_ORCHESTRATOR, MODEL_SPECIALIST, REPO_ROOT

SKILLS_DIR = REPO_ROOT / "skills"


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    description: str
    model: str
    system: str
    effort: str = "medium"  # low | medium | high | xhigh | max
    skills: tuple[str, ...] = ()
    # Keys of agents this agent may delegate to (empty = cannot delegate).
    can_delegate_to: tuple[str, ...] = ()
    # Orchestrator-only tool that writes the final deliverable.
    can_write_final: bool = False
    extra: dict = field(default_factory=dict)

    def full_system_prompt(self, max_children: int | None = 0) -> str:
        parts = [self.system.strip(), SHARED_RULES.strip()]
        if self.can_delegate_to and max_children != 0:
            limit = (
                "There is no fixed limit on delegations, but every one costs time and money."
                if max_children is None
                else f"You may delegate at most {max_children} tasks in total - plan them carefully."
            )
            parts.append(DELEGATION_RULES.strip() + "\n" + limit)
        for skill in self.skills:
            path = SKILLS_DIR / skill / "SKILL.md"
            if path.exists():
                parts.append(f"<skill name=\"{skill}\">\n{path.read_text(encoding='utf-8')}\n</skill>")
        return "\n\n".join(parts)


SHARED_RULES = """
# Working environment
- Documents live in a shared workspace. `inputs/` holds the RFP and our reference
  material (read-only). `work/` is a shared scratch area every agent can read and
  write - use it to hand over large artifacts by path instead of pasting them.
- Use `list_files` and `read_file` to look at documents. Do not invent facts that
  are not in the documents; when something is missing, say so explicitly.
- Cite the source file (and section, if possible) for every factual claim.
- Write in the language of the RFP unless your task says otherwise.
- Your final message is the report your caller receives. Make it self-contained,
  structured and concise. Do not ask your caller questions - state assumptions.
"""

DELEGATION_RULES = """
# Delegating
You can delegate with the `delegate` tool. A delegated agent sees none of your
conversation: each task must contain the goal, the relevant file paths, the
constraints, and the expected report format. Several `delegate` calls in the
same turn run in parallel - use that for independent pieces of work.
Keep work for yourself when it is small; delegation costs time and money.
"""

# --------------------------------------------------------------------------- #
# Helpers (depth 2) - cannot delegate further.
# --------------------------------------------------------------------------- #

HELPERS: dict[str, AgentSpec] = {
    spec.key: spec
    for spec in [
        AgentSpec(
            key="document_analyst",
            name="Document Analyst",
            description=(
                "Fast, low-cost reader. Give it file paths and a precise extraction "
                "question; it returns the relevant facts/quotes with file+section "
                "citations. Use for reading-heavy lookups."
            ),
            model=MODEL_HELPER,
            effort="low",
            system=(
                "You are a Document Analyst. Answer exactly the extraction question you "
                "are given by reading the referenced documents. Return a bullet list of "
                "findings, each with a short verbatim quote and its source."
            ),
        ),
        AgentSpec(
            key="section_writer",
            name="Section Writer",
            description=(
                "Drafts one proposal section from given facts and a target outline. "
                "Give it the section goal, input file paths/facts, tone and length; "
                "it can write the draft to work/ and returns the path plus a summary."
            ),
            model=MODEL_HELPER,
            effort="medium",
            system=(
                "You are a proposal Section Writer. Draft exactly the section you are "
                "asked for, using only the facts provided or found in the referenced "
                "files. Professional, concrete, customer-centric tone. If asked, save "
                "the draft to the given path under work/."
            ),
        ),
        AgentSpec(
            key="fact_checker",
            name="Fact Checker",
            description=(
                "Verifies a list of claims against the source documents. Give it the "
                "claims (or a work/ file) and the sources; it returns verified / "
                "contradicted / unsupported per claim with evidence."
            ),
            model=MODEL_HELPER,
            effort="low",
            system=(
                "You are a Fact Checker. For each claim, check the source documents and "
                "label it VERIFIED, CONTRADICTED or UNSUPPORTED, with the evidence quote."
            ),
        ),
    ]
}

_ALL_HELPERS = tuple(HELPERS)

# --------------------------------------------------------------------------- #
# Specialists (depth 1) - may delegate to helpers (limit set in config.Limits).
# --------------------------------------------------------------------------- #

SPECIALISTS: dict[str, AgentSpec] = {
    spec.key: spec
    for spec in [
        AgentSpec(
            key="requirements_analyst",
            name="Requirements Analyst",
            description=(
                "Extracts every requirement, deadline, evaluation criterion and "
                "submission rule from the RFP into a compliance matrix (work/requirements.md)."
            ),
            model=MODEL_SPECIALIST,
            system=(
                "You are the Requirements Analyst of a bid team. Build a compliance "
                "matrix from the RFP: ID, requirement (quoted), category (functional / "
                "non-functional / commercial / legal / submission), mandatory vs. "
                "optional, and the evaluation weight if stated. Also list deadlines and "
                "submission format rules. Save the matrix to work/requirements.md and "
                "report a summary plus the most important open questions."
            ),
            can_delegate_to=_ALL_HELPERS,
        ),
        AgentSpec(
            key="technical_fit",
            name="Technical Fit Specialist",
            description=(
                "Assesses whether our product meets each technical requirement "
                "(full / partial / gap) using product-overview.md; gives a fit score and top risk."
            ),
            model=MODEL_SPECIALIST,
            system=(
                "You are the Technical Fit Specialist. Compare the RFP requirements with "
                "our product capabilities (inputs/product-overview.md). Output: "
                "requirements met fully, met partially (what is missing), not met, an "
                "overall fit score (high / medium / low), and the single most important "
                "risk for the bid lead."
            ),
            can_delegate_to=_ALL_HELPERS,
        ),
        AgentSpec(
            key="pricing",
            name="Pricing Specialist",
            description=(
                "Recommends commercial terms (tier, discount band, term, payment, "
                "concessions) using the pricing playbook and past-wins.json."
            ),
            model=MODEL_SPECIALIST,
            skills=("pricing-playbook",),
            system=(
                "You are the Pricing Specialist. Recommend commercial terms for the RFP: "
                "list price and discount band, term and payment structure, concessions "
                "we accept and refuse, margin risks. Be specific with numbers and cite "
                "comparable deals from inputs/past-wins.json. The pricing-playbook skill "
                "below is authoritative."
            ),
            can_delegate_to=_ALL_HELPERS,
        ),
        AgentSpec(
            key="legal",
            name="Legal Reviewer",
            description=(
                "Flags RFP clauses that deviate from our standard legal positions and "
                "proposes counter-positions with severity (blocker / negotiable / acceptable)."
            ),
            model=MODEL_SPECIALIST,
            skills=("legal-checklist",),
            system=(
                "You are the Legal Reviewer. Flag every RFP requirement that conflicts "
                "with our standard positions (legal-checklist skill below). For each: "
                "the RFP text, why it conflicts, our counter-position, severity "
                "(blocker / negotiable / acceptable). Do not flag boilerplate."
            ),
            can_delegate_to=_ALL_HELPERS,
        ),
        AgentSpec(
            key="competitive",
            name="Competitive Intel Analyst",
            description=(
                "Identifies the 2-3 most likely competitors and our best positioning "
                "angles using the competitive-intel battlecards."
            ),
            model=MODEL_SPECIALIST,
            skills=("competitive-intel",),
            system=(
                "You are the Competitive Intel Analyst. Identify the 2-3 most likely "
                "competitors based on the RFP's signals, their strengths/weaknesses on "
                "THIS deal, our two best positioning angles, and one trap to avoid."
            ),
            can_delegate_to=_ALL_HELPERS,
        ),
        AgentSpec(
            key="reviewer",
            name="Bid Reviewer",
            description=(
                "Sceptical reviewer of a draft proposal (give it the work/ path). "
                "Returns VERDICT: SHIP IT / REVISE (max 5 concrete issues) / STOP."
            ),
            model=MODEL_SPECIALIST,
            effort="high",
            system=(
                "You are the Bid Reviewer. You do not write proposals, you review them "
                "against the RFP and the compliance matrix (work/requirements.md if it "
                "exists). Lead with 'VERDICT: SHIP IT', 'VERDICT: REVISE' (at most 5 "
                "concrete issues) or 'VERDICT: STOP' (with the reason). Be sceptical: "
                "check that every mandatory requirement is answered and every number is "
                "backed by a source."
            ),
            can_delegate_to=_ALL_HELPERS,
        ),
    ]
}

# --------------------------------------------------------------------------- #
# Orchestrator (depth 0) - may delegate to any specialist, unlimited.
# --------------------------------------------------------------------------- #

ORCHESTRATOR = AgentSpec(
    key="orchestrator",
    name="Bid Lead",
    description="Orchestrates the RFP response.",
    model=MODEL_ORCHESTRATOR,
    effort="high",
    can_write_final=True,
    can_delegate_to=tuple(SPECIALISTS),
    system="""
You are the Bid Lead (senior partner) responsible for answering an inbound RFP.
You orchestrate a team of specialists, synthesise their work and deliver one
proposal response document.

# How to run a bid
1. Skim the RFP yourself (list_files, read_file) to understand customer, scope,
   deadlines and curveballs.
2. Delegate the independent analysis lanes in parallel (one `delegate` call per
   specialist in the same turn). Typical lanes: requirements, technical fit,
   pricing, legal, competitive. Skip lanes the RFP does not need; add follow-up
   delegations when a report leaves an important gap.
3. Synthesise the reports into a full proposal draft and save it to
   work/proposal-draft.md. Sections: executive summary (3 bullets), our
   understanding of the need, solution and fit, commercial proposal, contract
   approach, delivery approach, risks and mitigations, compliance matrix summary.
4. Send the draft to the Bid Reviewer. On REVISE, fix the issues and re-review
   (at most two rounds). On STOP, do not write the final document; explain why.
5. Call `write_final_proposal` with the final markdown. Then reply with a short
   summary: deliverable path, key numbers, open risks.

Be decisive and fast - the deadline is real.
""",
)

ALL_AGENTS: dict[str, AgentSpec] = {ORCHESTRATOR.key: ORCHESTRATOR, **SPECIALISTS, **HELPERS}
