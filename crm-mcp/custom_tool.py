"""
Custom-Tool variant of the synthetic CRM (fallback while no public MCP URL exists).

Managed Agents don't run custom tools themselves: the agent emits
`agent.custom_tool_use`, our client runs the query and answers with
`user.custom_tool_result`. This module provides both halves for that:

- CRM_TOOLS: tool definitions to put into the Pricing Specialist's `tools`
- is_crm_tool / run_crm_tool: execute a tool call, return the result text

Same logic as the MCP server (crm_core.py), so switching to MCP later only
changes how the Pricing Specialist is wired up.
"""

import json

import crm_core

CRM_TOOLS = [
    {
        "type": "custom",
        "name": "search_past_deals",
        "description": (
            "Search past deals (wins and losses) in the CRM. All filters are "
            "optional and combined with AND. Returns discount, term, payment "
            "terms, competitors and why we won or lost. Use it to anchor "
            "discount recommendations on comparable deals. Any size filter "
            "excludes lost deals (they have no deal size)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "industry": {
                    "type": "string",
                    "description": 'Case-insensitive substring, e.g. "industrial".',
                },
                "competitor": {
                    "type": "string",
                    "description": 'Case-insensitive competitor name, e.g. "Snowflake".',
                },
                "min_annual_usd": {"type": "number", "description": "Minimum annual deal size in USD."},
                "max_annual_usd": {"type": "number", "description": "Maximum annual deal size in USD."},
                "outcome": {"type": "string", "enum": ["won", "lost"], "description": "Only won or only lost deals."},
            },
        },
    },
    {
        "type": "custom",
        "name": "get_deal",
        "description": "Get the full record of one past deal by customer name (substring match).",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer": {"type": "string", "description": 'Customer name, e.g. "Initech".'},
            },
            "required": ["customer"],
        },
    },
]

_HANDLERS = {
    "search_past_deals": crm_core.search_past_deals,
    "get_deal": crm_core.get_deal,
}


def is_crm_tool(name: str) -> bool:
    return name in _HANDLERS


def run_crm_tool(name: str, tool_input: dict) -> str:
    """Execute a CRM tool call and return the result as text for user.custom_tool_result."""
    try:
        return json.dumps(_HANDLERS[name](**(tool_input or {})), indent=2, ensure_ascii=False)
    except TypeError as exc:  # unknown/missing argument from the model
        return json.dumps({"error": f"Bad arguments for {name}: {exc}"})
