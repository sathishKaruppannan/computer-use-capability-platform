from pathlib import Path

import pytest

from capability_platform.capabilities.registry import CapabilityRegistry
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import CapabilityDescriptor, RiskLevel
from capability_platform.policy.engine import PolicyEngine, PolicyViolation, default_policy


def test_example_artifact_is_valid():
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    assert artifact.qualified_id == "lookup-member-savings-balance.v1"
    assert artifact.inputs[0].name == "memberId"
    assert artifact.outputs[0].name == "savingsBalance"


def test_policy_blocks_unknown_host():
    with pytest.raises(PolicyViolation):
        PolicyEngine(default_policy()).authorize_url("https://evil.example")


def test_semantic_registry_prefers_balance_capability():
    registry = CapabilityRegistry(
        [
            CapabilityDescriptor(
                id="balance",
                name="Savings balance",
                description="Read member deposit amount",
                source="computer_use",
                input_schema={},
                output_schema={},
                risk=RiskLevel.READ_ONLY,
                tags=["account", "balance"],
            ),
            CapabilityDescriptor(
                id="note",
                name="Create note",
                description="Write a servicing comment",
                source="local_tool",
                input_schema={},
                output_schema={},
                risk=RiskLevel.REVERSIBLE,
                tags=["note"],
            ),
        ]
    )
    assert registry.search("get member savings balance")[0][0].id == "balance"
