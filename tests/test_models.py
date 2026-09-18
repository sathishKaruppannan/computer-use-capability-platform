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


def test_registry_accepts_an_injected_embedding_provider():
    """The placeholder extension point for a real embedding model (OpenAI/Voyage/local) -- see
    capabilities/registry.py::_embedding's docstring. Default behavior must be unchanged (proven
    above); this proves the injection point itself actually works, with a trivial fake provider
    standing in for a real one -- resolver.py/ranking.py need zero changes either way, since they
    only ever see the float vector this returns."""
    calls: list[str] = []

    def _fake_embed(text: str) -> list[float]:
        calls.append(text)
        # A one-hot vector keyed by whether "note" appears -- deliberately NOT the real hashing
        # trick, so a search result that only makes sense under this fake provider proves it was
        # actually used, not silently ignored in favor of the default.
        return [1.0, 0.0] if "note" in text.lower() else [0.0, 1.0]

    descriptors = [
        CapabilityDescriptor(
            id="balance",
            name="Savings balance",
            description="Read member deposit amount",
            source="computer_use",
            input_schema={},
            output_schema={},
            risk=RiskLevel.READ_ONLY,
            tags=[],
        ),
        CapabilityDescriptor(
            id="note",
            name="Create note",
            description="Write a servicing comment",
            source="local_tool",
            input_schema={},
            output_schema={},
            risk=RiskLevel.REVERSIBLE,
            tags=[],
        ),
    ]
    registry = CapabilityRegistry(descriptors, embed_fn=_fake_embed)

    assert calls, "the injected embedding provider must be called while registering capabilities"
    assert registry.search("write a servicing note")[0][0].id == "note"
    assert registry.search("get the balance")[0][0].id == "balance"


def test_build_registry_defaults_to_the_hashing_trick_embedding():
    """Backward compatibility: build_registry()'s new embed_fn parameter defaults to the same
    function used before this parameter existed, so every existing caller is unaffected."""
    from capability_platform.capabilities.registry import _embedding, build_registry

    registry = build_registry(ArtifactStore(Path("artifacts")))
    assert registry._embed is _embedding
