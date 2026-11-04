"""
Synthetic CRM logic — no MCP or Managed-Agents dependency.

Reads synthetic-data/past-wins.json (single source of truth). Used by server.py
(MCP) and usable directly as a Custom Tool handler if MCP hosting isn't possible.
"""

import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "synthetic-data" / "past-wins.json"


def _load_deals() -> list[dict]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))["comparable_deals"]


def _is_won(deal: dict) -> bool:
    return deal.get("won_on") is not None


def search_past_deals(
    industry: str | None = None,
    competitor: str | None = None,
    min_annual_usd: float | None = None,
    max_annual_usd: float | None = None,
    outcome: str | None = None,
) -> dict:
    """Filter past deals. All filters optional, combined with AND.

    Lost deals have no deal size (0), so any size filter excludes them.
    """
    hits = []
    for d in _load_deals():
        won = _is_won(d)
        if industry and industry.lower() not in d.get("industry", "").lower():
            continue
        if competitor and not any(
            competitor.lower() in c.lower() for c in d.get("primary_competitors", [])
        ):
            continue
        if outcome and (outcome == "won") != won:
            continue
        if min_annual_usd is not None and (not won or d["deal_size_annual_usd"] < min_annual_usd):
            continue
        if max_annual_usd is not None and (not won or d["deal_size_annual_usd"] > max_annual_usd):
            continue
        hits.append(d)
    return {"count": len(hits), "deals": hits}


def get_deal(customer: str) -> dict:
    """Full record of one deal by customer name (case-insensitive substring)."""
    for d in _load_deals():
        if customer.lower() in d.get("customer", "").lower():
            return d
    return {"error": f'No deal found for customer matching "{customer}".'}
