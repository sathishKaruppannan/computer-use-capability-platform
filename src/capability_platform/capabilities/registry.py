import hashlib
import math
import re
from collections.abc import Iterable

from capability_platform.models import CapabilityDescriptor


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
