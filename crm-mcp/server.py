"""
Synthetic CRM as a remote MCP server (streamable HTTP, stateless, bearer auth).

Run locally:
    export CRM_MCP_TOKEN="some-long-random-string"      # or put it in crm-mcp/.env
    python crm-mcp/server.py                            # -> http://127.0.0.1:8765/mcp

Managed Agents can only reach public HTTPS URLs, so for the real swarm this has
to be reachable from the internet (hosting or tunnel). Synthetic data only.
"""

import hmac
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crm_core  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

HOST = os.environ.get("CRM_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("CRM_MCP_PORT", "8765"))

mcp = FastMCP(
    "synthetic-crm",
    stateless_http=True,
    json_response=True,
    host=HOST,
    port=PORT,
)


@mcp.tool()
def search_past_deals(
    industry: str | None = None,
    competitor: str | None = None,
    min_annual_usd: float | None = None,
    max_annual_usd: float | None = None,
    outcome: str | None = None,
) -> dict:
    """Search past deals (wins and losses) in the CRM.

    All filters are optional and combined with AND. Returns discount, term,
    payment terms, competitors and why we won or lost — use it to anchor
    discount recommendations on comparable deals.

    Args:
        industry: Case-insensitive substring, e.g. "industrial".
        competitor: Case-insensitive competitor name, e.g. "Snowflake".
        min_annual_usd: Minimum annual deal size in USD (excludes lost deals).
        max_annual_usd: Maximum annual deal size in USD (excludes lost deals).
        outcome: "won" or "lost".
    """
    return crm_core.search_past_deals(
        industry, competitor, min_annual_usd, max_annual_usd, outcome
    )


@mcp.tool()
def get_deal(customer: str) -> dict:
    """Get the full record of one past deal by customer name (substring match).

    Args:
        customer: Customer name, e.g. "Initech".
    """
    return crm_core.get_deal(customer)


class BearerAuth:
    """Pure-ASGI bearer check in front of the MCP app."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            auth = headers.get(b"authorization", b"").decode()
            supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if not hmac.compare_digest(supplied, self.token):
                resp = JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await resp(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app():
    token = os.environ.get("CRM_MCP_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("Set CRM_MCP_TOKEN (min. 16 chars) in the environment or crm-mcp/.env.")
    return BearerAuth(mcp.streamable_http_app(), token)


if __name__ == "__main__":
    uvicorn.run(build_app(), host=HOST, port=PORT)
