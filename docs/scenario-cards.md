# Scenario Cards — Option 3

Each team picks ONE scenario. Each is shaped like real services-firm work: a coordinator who orchestrates and 3-5 specialists who own lanes.

---

## Card A — Deal Desk (default scenario, fully wired in starter code)

**Coordinator:** "Senior Partner — Deal Desk Lead"
- Reads an inbound RFP
- Routes work to specialists
- Synthesises specialist outputs into a branded proposal doc

**Specialists:**
1. **Pricing Specialist** (skill: pricing-playbook) — decides commercial terms based on RFP scope and past wins
2. **Legal Reviewer** (skill: legal-checklist) — flags risky RFP requirements and recommends contract positions
3. **Technical Fit** (skill: product-overview) — assesses whether our product covers the RFP's requirements
4. **Competitive Intel** (skill: competitive-intel) — identifies which competitors are likely in this deal and how to position

**The trigger:** `synthetic-data/rfp-acme-corp.md` (an RFP from Acme Corp for an enterprise data platform)

**The deliverable:** A branded Word document at `outputs/proposal-response.docx`

---

## Card B — M&A Diligence Lite

**Coordinator:** "M&A Lead"
- Reads a deal memo and the target's data room
- Routes diligence work to specialists
- Produces a structured risk-and-recommendation memo

**Specialists:**
1. **Financial Analyst** — reviews the target's financials, flags concerns
2. **Legal Diligence** — scans contracts for change-of-control clauses, IP issues, litigation
3. **Tech Stack Assessor** — evaluates technical debt, integration complexity
4. **People & Culture** — assesses leadership, retention risk

**The trigger:** A synthetic data room (you'll need to extend `synthetic-data/` for this one)

**The deliverable:** A diligence memo in docx

---

## Card C — Hire-to-Onboard Orchestrator

**Coordinator:** "Onboarding Lead"
- Takes a new hire's profile and start date
- Coordinates the four functions that have to be ready by day 1

**Specialists:**
1. **Recruiter** — confirms offer terms, captures references status
2. **IT Provisioning** — generates the laptop + accounts checklist
3. **Onboarding Buddy Match** — picks a buddy based on team and seniority
4. **Welcome Packet** — generates personalised welcome content

**The trigger:** A synthetic new-hire-profile.md

**The deliverable:** A day-1 readiness pack in docx

---

## Picking guidance

| If your team is... | Pick |
| --- | --- |
| Just want the cleanest path | A (Deal Desk — code is ready) |
| Most senior partner audience | B (M&A — gravitas) |
| Most relatable to HR / people-ops clients | C (Hiring) |
