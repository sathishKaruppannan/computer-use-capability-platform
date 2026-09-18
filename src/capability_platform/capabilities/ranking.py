"""Capability candidate scoring. Source priority is a data table, not branching logic -- per
CLAUDE.md's rule not to add source-specific branches when a new capability source is added."""

from __future__ import annotations

from capability_platform.models import CapabilityDescriptor

# API > local deterministic tool > approved MCP tool > existing skill/workflow > existing
# computer-use artifact, per the required candidate priority order.
_SOURCE_PRIORITY: dict[str, float] = {
    "api": 1.00,
    "local_tool": 0.90,
    "mcp_tool": 0.80,
    "skill": 0.70,
    "computer_use": 0.60,
}


def score(
    descriptor: CapabilityDescriptor,
    semantic_score: float,
    latency_penalty: float = 0.0,
    cost_penalty: float = 0.0,
) -> float:
    base_priority = _SOURCE_PRIORITY.get(descriptor.source, 0.5)
    trust_bonus = 1.0 if descriptor.trust == "approved" else 0.5
    return (
        0.35 * base_priority
        + 0.30 * semantic_score
        + 0.20 * descriptor.reliability
        + 0.15 * trust_bonus
        - latency_penalty
        - cost_penalty
    )
