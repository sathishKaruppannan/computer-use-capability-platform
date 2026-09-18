from __future__ import annotations

from pathlib import Path
from typing import Protocol

from capability_platform.access.models import TenantCredential

# Matches exactly what agent/discovery.py::_credential_input_specs produces for a login-gated
# artifact. "username" is included even though it isn't marked sensitive=True on its own
# ParameterSpec (it isn't a secret by itself) -- it's still part of the credential pair stored
# here, not something a plan step should need to declare. Scoped to username/password only for
# now, per the current auth mode this system actually drives during discovery/replay.
CREDENTIAL_FIELD_NAMES = frozenset({"username", "password"})


class TenantCredentialStore(Protocol):
    def get(self, capability_id: str, client_id: str) -> TenantCredential | None: ...
    def save(self, credential: TenantCredential) -> Path: ...


class JSONTenantCredentialStore:
    """One JSON file per (capability_id, client_id) pair under `root` -- mirrors
    JSONCredentialStore's shape exactly. Never written into an artifact or an evidence log;
    looked up only at execution time (capabilities/executor.py) and injected directly into the
    replay inputs, the same way discovery already injects extra_known_values."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, capability_id: str, client_id: str) -> Path:
        return self.root / f"{capability_id}__{client_id}.json"

    def get(self, capability_id: str, client_id: str) -> TenantCredential | None:
        path = self._path(capability_id, client_id)
        if not path.exists():
            return None
        return TenantCredential.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, credential: TenantCredential) -> Path:
        path = self._path(credential.capability_id, credential.client_id)
        path.write_text(credential.model_dump_json(indent=2), encoding="utf-8")
        return path
