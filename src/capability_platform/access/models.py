from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from capability_platform.models import ServiceType


class ClientCredential(BaseModel):
    client_id: str
    password_hash: str
    password_salt: str
    authorized_service_types: list[ServiceType]
    is_admin: bool = False
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TenantCredential(BaseModel):
    """Target-system login credentials for one (capability_id, client_id) pair -- lets the same
    login-gated capability be replayed by multiple clients, each with their own stored
    credentials, rather than one shared secret embedded in the artifact itself.

    Deliberately plaintext at rest, unlike ClientCredential's one-way password hash: this value
    has to be *retrieved* and typed into a real login form during replay, not just verified. A
    production version would encrypt this at rest in a real secrets store with the same trust
    properties JSONCredentialStore already establishes for client credentials -- see REPORT.md's
    multi-tenant auth design (Phase 11) for that design; this is the demo-appropriate version of
    it, scoped to the one auth mode currently wired: username/password."""

    capability_id: str
    client_id: str
    username: str
    password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InquiryRecord(BaseModel):
    inquiry_id: str
    client_inquiry_id: str
    client_id: str
    goal: str | None = None
    service_type: ServiceType | None = None
    system_identifier: str | None = None
    capability_id: str | None = None
    reused_existing_capability: bool = False
    environment: Literal["production", "demo"] = "production"
    status: Literal["discovered", "executed", "failed"] = "discovered"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SystemRegistryEntry(BaseModel):
    system_identifier: str
    base_url: str
    vendor: str
    product: str
    description: str = ""
