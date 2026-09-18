"""Two shared fixtures for the agent/capability-resolution tests, reused across 6+ test files.
A deliberate, minimal deviation from this repo's normal no-conftest convention (every other test
file builds its own inline data) -- justified because these two fixtures would otherwise be
duplicated near-verbatim in test_capability_resolver.py, test_orchestrator.py, and others."""

from __future__ import annotations

from typing import Any

import pytest

from capability_platform.capabilities.registry import CapabilityRegistry
from capability_platform.llm.mock_provider import MockLLMProvider
from capability_platform.models import CapabilityDescriptor, RiskLevel


@pytest.fixture
def mock_intent_provider_factory():
    def _factory(response: dict[str, Any]) -> MockLLMProvider:
        return MockLLMProvider(response)

    return _factory


@pytest.fixture
def seeded_capability_registry() -> CapabilityRegistry:
    """One approved computer_use candidate, one blocked mcp_tool, one unapproved (discovered)
    candidate, and one input/output-incompatible candidate -- all superficially about the same
    topic (member savings balance) so semantic retrieval alone can't be what distinguishes them."""
    return CapabilityRegistry(
        [
            # local_tool, not computer_use: these fixtures exercise trust/approval filtering in
            # isolation, without needing a real ArtifactStore entry backing a computer_use id
            # (the real-artifact case is covered separately, against the actual artifacts/
            # directory, in test_existing_capability_is_selected_over_discovery).
            CapabilityDescriptor(
                id="approved-savings-balance",
                name="Approved savings balance lookup",
                description="Look up a member's savings balance",
                source="local_tool",
                input_schema={"memberId": {"type": "string", "required": True}},
                output_schema={"savingsBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="approved",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            ),
            CapabilityDescriptor(
                id="blocked-savings-balance-mcp",
                name="Blocked MCP savings balance tool",
                description="Look up a member's savings balance via a blocked MCP tool",
                source="mcp_tool",
                input_schema={"memberId": {"type": "string", "required": True}},
                output_schema={"savingsBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="blocked",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            ),
            CapabilityDescriptor(
                id="discovered-savings-balance",
                name="Newly discovered savings balance capability",
                description="Look up a member's savings balance, discovered but not yet approved",
                source="computer_use",
                input_schema={"memberId": {"type": "string", "required": True}},
                output_schema={"savingsBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="discovered",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            ),
            CapabilityDescriptor(
                id="incompatible-schema-savings",
                name="Incompatible savings balance tool",
                description="Look up a member's savings balance via a different, incompatible schema",
                source="local_tool",
                input_schema={"accountNumber": {"type": "string", "required": True}},
                output_schema={"currentBalance": {"type": "number"}},
                risk=RiskLevel.READ_ONLY,
                trust="approved",
                reliability=1.0,
                tags=["member", "savings", "balance"],
            ),
        ]
    )
