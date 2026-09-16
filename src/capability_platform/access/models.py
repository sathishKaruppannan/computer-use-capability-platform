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
