"""Response DTOs for the authenticated /v1 REST surface (api/v1_routes.py). Kept separate from
the route handlers themselves so the request/response contract is one clean, browsable place --
not mixed in with business logic. ExecutionResult (execute_v1's response) is deliberately NOT
duplicated here -- it's a core domain model (capability_platform.models), used well beyond just
this REST surface (CLI, legacy REST, MCP), so it stays imported from there directly. See
ExecutionResult / RunError in models.py for that response's field-by-field contract, including
how a client tells "failed, safe to requeue" apart from "failed, needs review first"."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from capability_platform.agent.models import (
    CapabilityExecutionResult,
    CapabilityResolution,
    ExecutionPlan,
    TaskIntent,
)
from capability_platform.models import (
    ApplicationBinding,
    Checkpoint,
    OutputSpec,
    ParameterSpec,
    RunStatus,
    ServiceType,
    Step,
)


class AgentResultSummary(BaseModel):
    status: RunStatus = Field(description="Overall run status, aggregated across every plan step.")
    outputs: dict[str, Any] = Field(description="Deterministically aggregated canonical outputs.")
    business_code: str | None = Field(default=None, description="First business outcome code encountered, if any.")
    synthesized_text: str = Field(
        description="Grounded synthesis of the canonical outputs -- templated, never LLM-derived."
    )


class AgentExecuteResponse(BaseModel):
    run_id: str
    intent: TaskIntent
    plan: ExecutionPlan
    resolutions: list[CapabilityResolution]
    execution: list[CapabilityExecutionResult]
    result: AgentResultSummary


class AgentPlanResponse(BaseModel):
    run_id: str
    intent: TaskIntent
    plan: ExecutionPlan
    resolutions: list[CapabilityResolution]


class DiscoverV1Response(BaseModel):
    capability_id: str = Field(
        description="Qualified id (id.vN) of the capability to invoke next via "
        "POST /v1/capabilities/{capability_id}/execute."
    )
    inquiry_id: str = Field(
        description="Server-generated id for this discovery inquiry, for audit/support lookup -- "
        "distinct from the caller's own client_inquiry_id."
    )
    reused_existing_capability: bool = Field(
        description="True: an already-approved capability matched (service_type, "
        "system_identifier) and was reused with zero LLM calls -- possibly discovered by a "
        "different client entirely. False: no match existed, so a live Claude discovery run "
        "produced a brand-new draft artifact that still needs admin approval before it is "
        "callable (see approval_required)."
    )
    lifecycle: str = Field(
        description="Artifact lifecycle state (draft, validating, approved, active, degraded, "
        "deprecated). Only lifecycles in AGENT_EXPOSABLE_LIFECYCLES may be executed."
    )
    approval_required: bool = Field(
        description="True when `lifecycle` is not yet in AGENT_EXPOSABLE_LIFECYCLES -- calling "
        "execute now will fail with 403 until an admin approves it via "
        "POST /v1/capabilities/{id}/approve."
    )


class ApproveV1Response(BaseModel):
    capability_id: str = Field(description="Qualified id (id.vN) of the artifact just approved.")
    lifecycle: str = Field(description="Lifecycle state after approval (always 'approved').")


class SystemSummary(BaseModel):
    system_identifier: str = Field(
        description="Key used as DiscoverV1Request.system_identifier to target this system."
    )
    base_url: str = Field(description="Vendor-reference base URL registered for this system.")
    vendor: str = Field(description="Vendor name, for display and fingerprint matching.")
    product: str = Field(description="Product name, for display and fingerprint matching.")
    description: str = Field(description="Free-text description shown to a human picking a system.")


class SystemListResponse(BaseModel):
    systems: list[SystemSummary] = Field(
        description="Every system registered in config/system_registry.json. Unauthenticated "
        "endpoint -- the registry holds no secrets, and a client needs this just to find a valid "
        "system_identifier before it can call anything else."
    )


class PendingCapabilitySummary(BaseModel):
    capability_id: str = Field(description="Qualified id (id.vN) of the pending artifact.")
    name: str = Field(description="Human-readable capability name.")
    lifecycle: str = Field(
        description="Current lifecycle state (not yet in AGENT_EXPOSABLE_LIFECYCLES, which is "
        "why it's in this queue)."
    )
    service_type: ServiceType | None = Field(
        description="Authorization scope this capability will require once approved, or None "
        "for a legacy artifact discovered before this field existed."
    )
    system_identifier: str | None = Field(
        description="Target system this capability was discovered against, or None for a "
        "legacy artifact discovered before this field existed."
    )
    created_at: datetime = Field(description="UTC timestamp the artifact was first discovered.")
    discovered_by: str = Field(description="Identity of the discovery agent/run that produced it.")


class PendingCapabilityListResponse(BaseModel):
    capabilities: list[PendingCapabilitySummary] = Field(
        description="Every artifact awaiting admin approval, admin-only (403 for a non-admin "
        "credential)."
    )


class RequesterInfo(BaseModel):
    client_id: str = Field(description="Authenticated client that made this inquiry.")
    goal: str | None = Field(
        default=None,
        description="Natural-language goal the client asked for, if this inquiry triggered discovery.",
    )
    client_inquiry_id: str = Field(description="That client's own correlation id for the inquiry.")
    environment: str = Field(description="'production' or 'demo', as the client requested.")
    created_at: datetime = Field(description="UTC timestamp the inquiry was recorded.")


class CapabilityReviewResponse(BaseModel):
    capability_id: str = Field(description="Qualified id (id.vN) of the artifact under review.")
    name: str = Field(description="Human-readable capability name.")
    description: str = Field(description="Human-readable summary of what the capability does.")
    lifecycle: str = Field(description="Current lifecycle state.")
    service_type: ServiceType | None = Field(
        description="Authorization scope this capability requires, or None for a legacy artifact."
    )
    system_identifier: str | None = Field(
        description="Target system this capability runs against, or None for a legacy artifact."
    )
    application: ApplicationBinding = Field(
        description="Vendor/product/base_url/version binding, including any per-tenant overrides."
    )
    inputs: list[ParameterSpec] = Field(
        description="Typed input contract -- exactly what ExecuteV1Request.inputs must supply."
    )
    outputs: list[OutputSpec] = Field(
        description="Typed output contract -- what ExecutionResult.outputs will contain on success."
    )
    steps: list[Step] = Field(
        description="Ordered, declared replay steps a reviewer can audit before approving."
    )
    success: Checkpoint = Field(
        description="Final checkpoint that must pass for a run to be reported as 'success'."
    )
    created_at: datetime = Field(description="UTC timestamp the artifact was first discovered.")
    discovered_by: str = Field(description="Identity of the discovery agent/run that produced it.")
    tags: list[str] = Field(description="Free-form labels for search/filtering in review tooling.")
    requested_by: list[RequesterInfo] = Field(
        description="Every inquiry that has ever asked for this exact capability_id, oldest "
        "first -- including repeat callers that reused it, not just the one that triggered "
        "discovery."
    )
