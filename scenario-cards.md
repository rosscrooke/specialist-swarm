# Scenario — Option 3

The scenario, shaped like real services-firm work: a coordinator who orchestrates and 3-5 specialists who own lanes.

---

## Deal Desk (fully wired in starter code)

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
