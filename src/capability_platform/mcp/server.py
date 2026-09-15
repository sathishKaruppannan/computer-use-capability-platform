import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.mcpserver import MCPServer

from capability_platform.capabilities.store import AGENT_EXPOSABLE_LIFECYCLES
from capability_platform.models import CapabilityArtifact
from capability_platform.runtime import replay_engine, store

mcp = MCPServer("learned-computer-use-capabilities")

_INPUT_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


@mcp.tool()
def list_capabilities() -> list[dict[str, Any]]:
    """List approved deterministic capabilities learned from legacy applications."""
    return [
        {
            "id": item.qualified_id,
            "description": item.description,
            "inputs": [i.model_dump() for i in item.inputs],
        }
        for item in store().list_approved()
    ]


def _to_snake_case(name: str) -> str:
    """MCP tool params read as idiomatic Python kwargs; artifact ParameterSpec names are
    whatever the source app's own field naming used (e.g. 'memberId', camelCase from
    discovery). 'memberId' -> 'member_id'."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _build_capability_tool(artifact: CapabilityArtifact) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Builds one generic MCP tool from an artifact's own typed ParameterSpecs, replacing a
    hand-written function per capability. The MCP library derives each tool's JSON-schema
    input contract by introspecting `inspect.signature(fn)` (see func_metadata.py) — so a
    real `inspect.Signature`, not just annotations, is attached to the generic handler below;
    Python itself doesn't enforce it at call time, `**kwargs` still accepts whatever is passed."""
    specs = sorted(artifact.inputs, key=lambda spec: not spec.required)
    snake_to_original = {_to_snake_case(spec.name): spec.name for spec in specs}
    parameters = [
        inspect.Parameter(
            snake_name,
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=_INPUT_TYPES[spec.type],
            default=inspect.Parameter.empty if spec.required else None,
        )
        for snake_name, spec in zip(snake_to_original.keys(), specs, strict=True)
    ]

    async def _invoke(**kwargs: Any) -> dict[str, Any]:
        # Re-load at call time, not from the closed-over `artifact` — mirrors the original
        # hardcoded tool's behavior: a capability approved/deprecated after server startup is
        # picked up on the next call without needing a restart.
        current = store().load(artifact.qualified_id)
        if current.lifecycle not in AGENT_EXPOSABLE_LIFECYCLES:
            raise ValueError(f"Capability '{artifact.qualified_id}' is not approved for invocation")
        mapped_inputs = {
            snake_to_original[snake_name]: str(value)
            for snake_name, value in kwargs.items()
            if value is not None
        }
        result = await replay_engine().execute(current, mapped_inputs)
        return result.model_dump(mode="json")

    _invoke.__signature__ = inspect.Signature(parameters, return_annotation=dict[str, Any])
    _invoke.__doc__ = artifact.description
    _invoke.__name__ = artifact.id.replace("-", "_")
    return _invoke


def _register_capability_tools() -> None:
    """One MCP tool per distinct approved capability id — highest approved version wins if
    more than one version of the same id is approved at once."""
    latest_by_id: dict[str, CapabilityArtifact] = {}
    for artifact in store().list_approved():
        current = latest_by_id.get(artifact.id)
        if current is None or artifact.version > current.version:
            latest_by_id[artifact.id] = artifact

    for artifact in latest_by_id.values():
        mcp.add_tool(_build_capability_tool(artifact), name=artifact.id.replace("-", "_"))


_register_capability_tools()


if __name__ == "__main__":
    mcp.run(transport="stdio")
