---
name: competitive-intel
description: BTS-Synthetic competitive battlecards for the Enterprise Data Platform space. Use whenever assessing who else is likely competing for an RFP and how to position against them. Covers Databricks, Snowflake, Microsoft Fabric, and Google BigQuery as the four most common competitors we see in enterprise deals.
---

# Competitive Intelligence

Use this when the coordinator asks you to identify competitors and recommend positioning.

## Pattern matching: who's in the deal?

| RFP signal | Likely competitor |
| --- | --- |
| Lots of mentions of "Lakehouse architecture", "MLflow integration", "Delta tables" | **Databricks** |
| Heavy SQL emphasis, "data marketplace", "secure data sharing", existing Snowflake user mentioned | **Snowflake** |
| Customer is heavy Microsoft shop, Azure-only, mentions of Power BI integration | **Microsoft Fabric** |
| Customer is GCP-native, mentions BigQuery ML, Looker | **Google BigQuery** |
| RFP asks about open-source compatibility / no vendor lock-in | Possibly Databricks, possibly an open-source rival like Trino+Iceberg |

If two or more of these signals appear, both competitors are likely shortlisted.

## Battlecards

### vs. Databricks

**Their strengths:**
- Strong ML/AI story (MLflow, Mosaic)
- Lakehouse / Delta is genuinely good for very large-scale workloads
- Open file format reduces lock-in concern
- Brand momentum among data engineering teams

**Their weaknesses:**
- Total cost of ownership often surprises customers (compute spend ramps fast)
- Less mature on BI / analyst-friendly tooling
- Spark-based query latency for interactive analytics can be poor

**Our angles:**
- Lead with TCO: produce a 3-year cost projection. We win on predictable spend.
- Position on time-to-insight for analyst personas, not just engineers.
- Don't fight on ML breadth. Concede that and pivot.

**Trap to avoid:**
- Don't try to out-engineer them on Spark or Iceberg. You'll lose on technical ground.

---

### vs. Snowflake

**Their strengths:**
- Best-in-class analyst experience
- Mature data sharing
- "Just works" reputation

**Their weaknesses:**
- Expensive at scale (the standard procurement complaint)
- Less flexible for unstructured / semi-structured / real-time
- ML/AI story is bolted-on, not native

**Our angles:**
- Lead with workload coverage: real-time, semi-structured, unstructured.
- Highlight ML-native architecture.
- Run a TCO comparison at customer's projected scale — usually wins on year 2+.

**Trap to avoid:**
- Don't try to out-analyst-tool Snowflake on day 1. They've been polishing that experience for a decade.

---

### vs. Microsoft Fabric

**Their strengths:**
- E5 license inclusion makes the headline price look free
- Tight Power BI integration
- Already deployed in the customer's tenant

**Their weaknesses:**
- Maturity gaps in core capabilities (still catching up on basic features)
- Lock-in to Azure-only
- Performance consistency varies

**Our angles:**
- Honest TCO including Microsoft consulting hours
- Multi-cloud story (don't lock yourself in)
- Maturity: we've been doing this for 8 years; they've been doing it for 18 months.

**Trap to avoid:**
- Don't compete on Power BI integration. We integrate, they own.
- Don't dismiss the "free with E5" claim. Acknowledge it directly and reframe to TCO.

---

### vs. Google BigQuery

**Their strengths:**
- Truly serverless analytics — no cluster management
- Strong on standard SQL workloads
- Vertex AI integration is genuinely useful

**Their weaknesses:**
- GCP-only (deal-breaker for multi-cloud customers)
- Less mature governance / data-mesh story
- Streaming ingest costs add up

**Our angles:**
- Multi-cloud flexibility
- Governance and data-mesh maturity
- Workload portability

**Trap to avoid:**
- Don't claim better serverless than BigQuery. We're not.

## How to format your output

For each likely competitor:
1. Why they're likely in this deal (cite the RFP signals)
2. Their strengths AGAINST OUR ANGLES (not generic strengths)
3. Our two best positioning angles for THIS RFP specifically
4. One trap

Then a one-line summary: "Most likely shortlist: X, Y, Z. Our best opening move: [specific recommendation]."
