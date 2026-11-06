# BTS-Synthetic Enterprise Data Platform — Capability Map

Authoritative capability list for the Technical Fit Specialist. Use this to answer "do we cover this requirement?"

## Core architecture

- **Lakehouse** with native support for Delta, Iceberg, and Parquet file formats.
- **Object storage backend** — bring-your-own S3, Azure Blob, or GCS.
- **Compute is decoupled** from storage. Multiple compute engines available: SQL, Spark-equivalent, streaming.
- **Multi-cloud**: deployable on AWS, Azure, GCP. Multi-region within each cloud.
- **Self-hosted option** for sovereignty-sensitive customers.

## Ingest

- **Batch ETL**: 80+ connectors out of the box (Salesforce, SAP, NetSuite, common databases).
- **Real-time streaming**: native Kafka and Kinesis consumers. Tested up to 250K events/second on single-region deployments.
- **CDC** (change data capture) from major databases via Debezium-compatible connectors.

## Analytics

- **SQL** workloads: full ANSI SQL, sub-second on warmed caches up to 10TB.
- **Notebooks** for data scientists: Python, R, Scala.
- **BI integrations**: certified integrations with Power BI, Tableau, Looker, Qlik. Power BI is our most mature BI integration (we have a dedicated DirectQuery adapter).
- **Self-service prep**: low-code data prep UI for analyst personas.

## Governance

- **Unity-style catalog** for tables, models, dashboards.
- **Row-level + column-level security** with attribute-based access control.
- **Data residency**: per-table residency enforcement. EU data tables can be pinned to EU regions.
- **Audit logs**: every read and write logged, exportable to customer SIEM.
- **PII detection and masking** built-in.

## ML / AI

- **Model registry** with versioning.
- **Feature store** for offline + online serving.
- **Native model serving** with autoscaling.
- **Bring-your-own-model**: any HuggingFace, Anthropic, or OpenAI model can be called from within the platform.

## SLA

- **99.95% monthly uptime** on Enterprise tier.
- 99.99% available as a custom add-on with bespoke architecture — typically $80K-$120K/year premium and requires multi-region active-active.

## Compliance

- SOC 2 Type II
- ISO 27001
- HIPAA-eligible
- GDPR-aligned (DPA available)
- FedRAMP Moderate (US Gov tier only)

## Where we're WEAK

Important honest list — use this when assessing fit.

- **Real-time analytics at sub-100ms latency**: we're not best-in-class here. We hit ~250ms-1s on streaming queries. If the RFP demands sub-100ms, flag as "partial fit."
- **Geospatial workloads**: basic support only, no advanced geospatial indexing.
- **Graph workloads**: not natively supported. Customers do this in separate graph databases.
- **No native Power Apps connector** (Power BI yes, Power Apps no — customers usually OK with this).

## Implementation timeline (typical)

- **8 weeks** to first production workload for a customer with clean source systems.
- **16 weeks** for full migration from legacy warehouse like Teradata or Hadoop.
- **24 weeks** for very large, multi-region, multi-source customers.
