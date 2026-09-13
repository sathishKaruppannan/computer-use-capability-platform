"""Real MCP client/server integration test — spawns the server exactly as .mcp.json does
(`uv run python -m capability_platform.mcp.server`, stdio transport) and drives it with a
real MCP client session. Requires the live demo app for the tool invocation to succeed."""

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.e2e
async def test_mcp_server_lists_and_invokes_capability():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "capability_platform.mcp.server"],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = (await session.list_tools()).tools
        tool_names = {t.name for t in tools}
        assert {"list_capabilities", "lookup_member_savings_balance"} <= tool_names

        listed = await session.call_tool("list_capabilities", {})
        capabilities = listed.structured_content["result"]
        assert any(c["id"] == "lookup-member-savings-balance.v1" for c in capabilities)

        invoked = await session.call_tool(
            "lookup_member_savings_balance", {"member_id": "10002"}
        )
        result = invoked.structured_content
        assert result["status"] == "success"
        assert result["outputs"]["savingsBalance"] == 1220.0
