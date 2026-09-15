"""Calls the real generated MCP tool function directly (same object `_register_capability_tools`
would hand to `mcp.add_tool`), bypassing the stdio/JSON-RPC transport so it can be single-stepped
in a normal debugger without needing a second connected MCP client process.

Needs an approved capability on disk first: `uv run capability-platform approve
lookup-member-savings-balance.v1` (or run `make discover` then `approve`), and the demo app
running on port 8001 (`make demo`) since the tool call itself replays against it.

Used by the "Debug: MCP tool invocation (direct call)" launch config in .vscode/launch.json.
"""

import asyncio
from pathlib import Path

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.mcp.server import _build_capability_tool


async def main() -> None:
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    tool_fn = _build_capability_tool(artifact)
    result = await tool_fn(member_id="10002")
    print("RESULT:", result)


if __name__ == "__main__":
    asyncio.run(main())
