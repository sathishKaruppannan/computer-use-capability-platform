import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from capability_platform.runtime import replay_engine, store

mcp = FastMCP("learned-computer-use-capabilities")


@mcp.tool()
def list_capabilities() -> list[dict[str, Any]]:
    """List approved deterministic capabilities learned from legacy applications."""
    return [
        {
            "id": item.qualified_id,
            "description": item.description,
            "inputs": [i.model_dump() for i in item.inputs],
        }
        for item in store().list()
    ]


@mcp.tool()
def lookup_member_savings_balance(member_id: str) -> dict[str, Any]:
    """Deterministically look up a demo member's savings balance through the legacy UI."""
    artifact = store().load("lookup-member-savings-balance.v1")
    return asyncio.run(replay_engine().execute(artifact, {"memberId": member_id})).model_dump(
        mode="json"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
