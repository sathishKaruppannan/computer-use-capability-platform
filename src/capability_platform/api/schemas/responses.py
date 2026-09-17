"""Response DTOs for the authenticated /v1 REST surface (api/v1_routes.py). Kept separate from
the route handlers themselves so the request/response contract is one clean, browsable place --
not mixed in with business logic. ExecutionResult (execute_v1's response) is deliberately NOT
duplicated here -- it's a core domain model (capability_platform.models), used well beyond just
this REST surface (CLI, legacy REST, MCP), so it stays imported from there directly."""

from datetime import datetime

from pydantic import BaseModel

from capability_platform.models import (
    ApplicationBinding,
    Checkpoint,
    OutputSpec,
    ParameterSpec,
    ServiceType,
    Step,
)


class DiscoverV1Response(BaseModel):
    capability_id: str
    inquiry_id: str
    reused_existing_capability: bool
    lifecycle: str
    approval_required: bool


class ApproveV1Response(BaseModel):
    capability_id: str
    lifecycle: str


class SystemSummary(BaseModel):
    system_identifier: str
    base_url: str
    vendor: str
    product: str
    description: str


class SystemListResponse(BaseModel):
    systems: list[SystemSummary]


class PendingCapabilitySummary(BaseModel):
    capability_id: str
    name: str
    lifecycle: str
    service_type: ServiceType | None
    system_identifier: str | None
    created_at: datetime
    discovered_by: str


class PendingCapabilityListResponse(BaseModel):
    capabilities: list[PendingCapabilitySummary]


class RequesterInfo(BaseModel):
    client_id: str
    goal: str | None
    client_inquiry_id: str
    environment: str
    created_at: datetime


class CapabilityReviewResponse(BaseModel):
    capability_id: str
    name: str
    description: str
    lifecycle: str
    service_type: ServiceType | None
    system_identifier: str | None
    application: ApplicationBinding
    inputs: list[ParameterSpec]
    outputs: list[OutputSpec]
    steps: list[Step]
    success: Checkpoint
    created_at: datetime
    discovered_by: str
    tags: list[str]
    requested_by: list[RequesterInfo]
