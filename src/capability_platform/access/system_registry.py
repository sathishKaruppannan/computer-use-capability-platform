from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from capability_platform.access.models import SystemRegistryEntry

DEFAULT_SYSTEM_REGISTRY_PATH = Path("config/system_registry.json")


class SystemNotRegisteredError(RuntimeError):
    pass


class SystemRegistry(Protocol):
    def resolve(self, system_identifier: str) -> SystemRegistryEntry: ...
    def list(self) -> list[SystemRegistryEntry]: ...


class JSONSystemRegistry:
    """Admin-curated system_identifier -> base_url mapping, mirroring policy/engine.py's
    default_policy() convention rather than ArtifactStore's per-entity-file convention — this
    is the same *kind* of artifact as config/policy.json: an admin allowlist, not client-writable
    state. A client's system_identifier can only ever resolve to a URL an admin has pre-approved
    here; PolicyEngine.authorize_url() still independently re-checks that URL's host, so a
    client cannot cause automation to reach a host absent from either list."""

    def __init__(self, path: Path = DEFAULT_SYSTEM_REGISTRY_PATH) -> None:
        self.path = path
        self._entries = self._load()

    def _load(self) -> dict[str, SystemRegistryEntry]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            entry["systemIdentifier"]: SystemRegistryEntry(
                system_identifier=entry["systemIdentifier"],
                base_url=entry["baseUrl"],
                vendor=entry["vendor"],
                product=entry["product"],
                description=entry.get("description", ""),
            )
            for entry in data.get("systems", [])
        }

    def resolve(self, system_identifier: str) -> SystemRegistryEntry:
        try:
            return self._entries[system_identifier]
        except KeyError:
            raise SystemNotRegisteredError(system_identifier) from None

    def list(self) -> list[SystemRegistryEntry]:
        return list(self._entries.values())
