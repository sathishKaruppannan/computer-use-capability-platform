from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from typing import Protocol

from capability_platform.access.models import ClientCredential
from capability_platform.models import ServiceType

# OWASP 2023 guidance for PBKDF2-HMAC-SHA256. Stdlib-only: pyproject.toml has no
# password-hashing dependency today; argon2-cffi is the natural upgrade if this ever backs a
# real credential store instead of the JSON mock (see JSONCredentialStore).
PBKDF2_ITERATIONS = 600_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return derived.hex(), salt.hex()


def verify_password(password: str, password_hash: str, password_salt: str) -> bool:
    derived, _ = hash_password(password, bytes.fromhex(password_salt))
    return hmac.compare_digest(derived, password_hash)


class CredentialStore(Protocol):
    def get(self, client_id: str) -> ClientCredential | None: ...
    def authorize(self, credential: ClientCredential, service_type: ServiceType) -> bool: ...


class JSONCredentialStore:
    """One JSON file per client_id under `root` — mirrors ArtifactStore's shape exactly, so a
    real DB-backed CredentialStore implementation later is a drop-in change; callers only ever
    see the CredentialStore Protocol. save() only ever accepts an already-hashed
    ClientCredential — no plaintext password round-trips through this class."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, client_id: str) -> ClientCredential | None:
        path = self.root / f"{client_id}.json"
        if not path.exists():
            return None
        return ClientCredential.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, credential: ClientCredential) -> Path:
        path = self.root / f"{credential.client_id}.json"
        path.write_text(credential.model_dump_json(indent=2), encoding="utf-8")
        return path

    def authorize(self, credential: ClientCredential, service_type: ServiceType) -> bool:
        return service_type in credential.authorized_service_types
