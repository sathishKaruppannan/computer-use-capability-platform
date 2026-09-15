from __future__ import annotations

import json
from pathlib import Path

from capability_platform.models import CapabilityArtifact, ServiceType

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

    def find_approved_by_service_and_system(
        self, service_type: ServiceType, system_identifier: str
    ) -> CapabilityArtifact | None:
        """Cross-client reuse lookup: any APPROVED/ACTIVE capability already discovered for
        this exact (service_type, system_identifier) pair, regardless of which client
        originally triggered discovery. None signals the caller to run discovery."""
        for artifact in self.list_approved():
            if (
                artifact.service_type == service_type
                and artifact.system_identifier == system_identifier
            ):
                return artifact
        return None
