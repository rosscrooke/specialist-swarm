# Request for Proposal — Acme Corp Enterprise Data Platform

**From:** Acme Corp, Procurement Office (procurement@acme-synthetic.example)
**To:** Vendor — BTS-Synthetic
**Issued:** 2026-05-12
**Response due:** 2026-05-26 (14 days)
**Award expected:** 2026-06-30

## 1. About Acme Corp

Acme Corp is a global manufacturer of industrial sensors and IoT devices. Revenue ~$1.4B (2025). 7,200 employees across 18 countries. We operate manufacturing facilities in Mexico, Vietnam, and Romania, with R&D centres in the US (Austin) and Germany (Munich).

We are a Microsoft shop. Our primary cloud is Azure. We also have legacy on-premises data warehouses (Teradata) being decommissioned through 2027.

## 2. Scope

We are seeking an enterprise data platform to replace our current patchwork of on-premises warehouses and ad-hoc cloud analytics. The platform must support:

### 2.1 Workloads
- Real-time ingest from ~40,000 IoT devices in the field
- Batch ETL from 30+ internal sources
- BI and reporting for ~600 analysts and executives
- Self-service data preparation for ~150 data engineers
- Machine learning pipelines for predictive maintenance (planned, not active)

### 2.2 Scale
- ~280 TB current data volume
- ~12 TB / month growth rate
- Peak ingest: 80,000 events/second

### 2.3 Capabilities
- Native Power BI integration (this is non-negotiable — 600 users today)
- Multi-region deployment (primary EU, secondary US East)
- Data residency: EU customer data must remain in EU
- Lakehouse architecture preferred
- Open file formats (Parquet, Delta, Iceberg) for portability

## 3. Commercial requirements

### 3.1 Term
We are seeking a 3-year initial term with a 2-year renewal option. Pricing for the full 5-year horizon must be fixed at the time of contract signature, with no escalators.

### 3.2 Payment
Annual fees billed in advance, due Net 90.

### 3.3 Discount
The successful vendor must offer no less than 35% off published list pricing.

### 3.4 Most Favoured Nation
The vendor must warrant that pricing offered to Acme is no less favourable than pricing offered to any comparable customer for the duration of the contract.

### 3.5 Termination
Acme reserves the right to terminate the contract at any time, with or without cause, on 30 days' written notice. No early termination fees or penalties.

## 4. Contractual requirements

### 4.1 Liability
Vendor liability for any data breach is uncapped. Vendor must indemnify Acme for all costs, including notification costs, regulatory fines, and reputational damages.

### 4.2 Audit
Acme reserves the right to audit vendor's controls, facilities, and personnel without prior notice, up to four times per calendar year. Audit costs shall be borne by the vendor.

### 4.3 Service Levels
Vendor must commit to 99.99% monthly uptime. SLA failures of any duration shall entitle Acme to terminate the contract immediately, with full refund of fees paid in the affected month.

### 4.4 IP
All work product, including any custom development, configurations, and integrations created in the course of this engagement, shall vest in Acme Corp upon creation.

### 4.5 Subprocessors
Vendor shall obtain Acme's prior written consent before engaging any subprocessor for any part of the services. Consent may be withheld at Acme's sole discretion.

## 5. Evaluation criteria

| Criterion | Weight |
| --- | --- |
| Functional fit (workloads + capabilities) | 30% |
| Commercial terms (pricing + flexibility) | 25% |
| Total cost of ownership (3 + 2 years) | 20% |
| Implementation timeline and risk | 15% |
| Vendor financial stability + customer references | 10% |

## 6. Vendors being evaluated

We are also issuing this RFP to:
- Databricks
- Snowflake
- Microsoft (Fabric)
- A regional vendor we will not name in this document

## 7. Response format

Please respond by 2026-05-26 with:
- Executive summary (1 page)
- Technical proposal (no page limit)
- Commercial proposal with full pricing transparency for 5 years
- Implementation plan with key milestones
- Three customer references (similar scale + Power BI + Azure)
- Filled "Capability Matrix" attachment (not included in this synthetic — coordinator: assume it's filled separately)

## 8. Contact

Direct all questions and the response to: procurement@acme-synthetic.example
Procurement lead: Sarah Chen, VP Procurement
Technical lead: Marcus Webb, Chief Data Officer
