import hashlib
import math
import re
from collections.abc import Iterable

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import CapabilityArtifact, CapabilityDescriptor, RiskLevel


def _embedding(text: str, dimensions: int = 128) -> list[float]:
    """Dependency-free hashing embeddings for the POC; replaceable by a vector provider."""
    vector = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += -1.0 if digest[4] & 1 else 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


class CapabilityRegistry:
    def __init__(self, capabilities: Iterable[CapabilityDescriptor] = ()) -> None:
        self._items: dict[str, CapabilityDescriptor] = {}
        self._vectors: dict[str, list[float]] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: CapabilityDescriptor) -> None:
        self._items[capability.id] = capability
        content = " ".join([capability.name, capability.description, *capability.tags])
        self._vectors[capability.id] = _embedding(content)

    def search(self, intent: str, limit: int = 5) -> list[tuple[CapabilityDescriptor, float]]:
        query = _embedding(intent)
        candidates = []
        for key, capability in self._items.items():
            if capability.trust in {"blocked", "discovered"}:
                continue
            semantic = _cosine(query, self._vectors[key])
            score = (
                0.55 * semantic
                + 0.25 * capability.reliability
                + 0.20 * (1.0 if capability.trust == "approved" else 0.5)
            )
            candidates.append((capability, score))
        return sorted(candidates, key=lambda item: item[1], reverse=True)[:limit]

    def list(self) -> list[CapabilityDescriptor]:
        return list(self._items.values())


# Connects CapabilityRegistry to the real runtime (capabilities.resolver, agent.orchestrator)
# instead of leaving it wired into nothing but tests/test_models.py. Normalizes every existing
# capability source into CapabilityDescriptor here, once -- per CLAUDE.md's "do not add
# source-specific branches to the planner" rule, this is the one place that translates a source
# into the normalized model; the resolver/ranking downstream only ever sees CapabilityDescriptor.
_RISK_ORDER = (RiskLevel.READ_ONLY, RiskLevel.REVERSIBLE, RiskLevel.RISKY, RiskLevel.IRREVERSIBLE)


def _artifact_risk(artifact: CapabilityArtifact) -> RiskLevel:
    if not artifact.steps:
        return RiskLevel.READ_ONLY
    return max((step.risk for step in artifact.steps), key=_RISK_ORDER.index)


def _descriptor_from_artifact(artifact: CapabilityArtifact) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        id=artifact.qualified_id,
        name=artifact.name,
        description=artifact.description,
        source="computer_use",
        input_schema={
            spec.name: {"type": spec.type, "required": spec.required} for spec in artifact.inputs
        },
        output_schema={spec.name: {"type": spec.type} for spec in artifact.outputs},
        risk=_artifact_risk(artifact),
        # Guaranteed by ArtifactStore.list_approved() only ever returning
        # AGENT_EXPOSABLE_LIFECYCLES -- a draft artifact is never turned into a descriptor here.
        trust="approved",
        reliability=1.0,
        tags=artifact.tags,
    )


def _member_financial_summary_descriptor() -> CapabilityDescriptor:
    """The one existing composable skill (skills/member_financial_summary.py), normalized the
    same way an artifact is -- a static entry rather than something requiring a store lookup."""
    return CapabilityDescriptor(
        id="member-financial-summary",
        name="Member financial summary",
        description="Look up a member's identity and savings balance together.",
        source="skill",
        input_schema={"memberId": {"type": "string", "required": True}},
        output_schema={"memberId": {"type": "string"}, "savings": {"type": "object"}},
        risk=RiskLevel.READ_ONLY,
        trust="approved",
        reliability=1.0,
        tags=["member", "financial-summary", "skill"],
    )


def build_registry(
    artifact_store: ArtifactStore, extra: Iterable[CapabilityDescriptor] = ()
) -> CapabilityRegistry:
    """Builds a CapabilityRegistry from every currently-approved source: computer-use artifacts
    (ArtifactStore.list_approved()), the one existing skill, and any caller-supplied extras (the
    seam for future local_tool/mcp_tool/api descriptors -- never fabricated here)."""
    descriptors = [_descriptor_from_artifact(artifact) for artifact in artifact_store.list_approved()]
    descriptors.append(_member_financial_summary_descriptor())
    descriptors.extend(extra)
    return CapabilityRegistry(descriptors)
