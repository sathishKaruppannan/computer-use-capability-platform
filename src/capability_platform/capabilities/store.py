from __future__ import annotations

import json
from pathlib import Path

from capability_platform.models import CapabilityArtifact

# Lifecycle states safe to hand to an agent-facing surface (REST/MCP). draft/validating are
# pre-approval; degraded/deprecated are post-approval states an agent shouldn't newly invoke.
AGENT_EXPOSABLE_LIFECYCLES = frozenset({"approved", "active"})


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, artifact: CapabilityArtifact) -> Path:
        path = self.root / f"{artifact.qualified_id}.json"
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, qualified_id: str) -> CapabilityArtifact:
        path = self.root / f"{qualified_id}.json"
        return CapabilityArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[CapabilityArtifact]:
        """Every capability on disk, draft or not — for administrative/CLI visibility."""
        return [
            CapabilityArtifact.model_validate(json.loads(p.read_text()))
            for p in self.root.glob("*.json")
        ]

    def list_approved(self) -> list[CapabilityArtifact]:
        """Only capabilities safe to expose to an agent-facing surface (REST/MCP)."""
        return [a for a in self.list() if a.lifecycle in AGENT_EXPOSABLE_LIFECYCLES]
