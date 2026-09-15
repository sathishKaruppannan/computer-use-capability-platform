from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PromptVariant:
    """Mirrors CapabilityArtifact's id + version -> qualified_id convention (models.py), so a
    discovery run's provenance can cite exactly which prompt content produced it."""

    id: str
    version: int
    system_prompt: str
    action_tool: dict[str, Any]

    @property
    def qualified_id(self) -> str:
        return f"{self.id}.v{self.version}"
