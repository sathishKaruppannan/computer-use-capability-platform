from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from capability_platform.access.models import ClientCredential, InquiryRecord
from capability_platform.access.system_registry import SystemNotRegisteredError
from capability_platform.api.auth import authenticate_client, require_service_type
from capability_platform.capabilities.store import AGENT_EXPOSABLE_LIFECYCLES
from capability_platform.models import (
    ApplicationBinding,
    Checkpoint,
    ExecutionResult,
    OutputSpec,
    ParameterSpec,
    ServiceType,
    Step,
)
from capability_platform.runtime import (
    discovery_agent,
    inquiry_tracker,
    replay_engine,
    store,
    system_registry,
)

router = APIRouter(prefix="/v1", tags=["v1"])


class DiscoverV1Request(BaseModel):
    service_type: ServiceType
    system_identifier: str
    client_inquiry_id: str
    goal: str
    environment: Literal["production", "demo"] = "production"
    example_member_id: str = "10001"


class DiscoverV1Response(BaseModel):
    capability_id: str
    inquiry_id: str
    reused_existing_capability: bool
    lifecycle: str
    approval_required: bool


class ExecuteV1Request(BaseModel):
    client_inquiry_id: str
    inputs: dict[str, Any]


class ApproveV1Response(BaseModel):
    capability_id: str
    lifecycle: str


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


@router.post("/discover", response_model=DiscoverV1Response)
async def discover_v1(
    request: DiscoverV1Request,
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> DiscoverV1Response:
    require_service_type(request.service_type, credential)
    inquiry_id = str(uuid4())

    existing = store().find_approved_by_service_and_system(
        request.service_type, request.system_identifier
    )
    if existing is not None:
        # Cross-client reuse: this capability may have been discovered by a different
        # client entirely — no discovery, no LLM call, on this path.
        inquiry_tracker().record(
            InquiryRecord(
                inquiry_id=inquiry_id,
                client_inquiry_id=request.client_inquiry_id,
                client_id=credential.client_id,
                goal=request.goal,
                service_type=request.service_type,
                system_identifier=request.system_identifier,
                capability_id=existing.qualified_id,
                reused_existing_capability=True,
                environment=request.environment,
            )
        )
        return DiscoverV1Response(
            capability_id=existing.qualified_id,
            inquiry_id=inquiry_id,
            reused_existing_capability=True,
            lifecycle=existing.lifecycle,
            approval_required=existing.lifecycle not in AGENT_EXPOSABLE_LIFECYCLES,
        )

    try:
        system_entry = system_registry().resolve(request.system_identifier)
    except SystemNotRegisteredError as exc:
        raise HTTPException(
            400, f"Unknown system_identifier: {request.system_identifier}"
        ) from exc

    artifact = await discovery_agent(environment=request.environment).discover(
        request.goal, system_entry.base_url, request.example_member_id
    )
    artifact.service_type = request.service_type
    artifact.system_identifier = request.system_identifier
    store().save(artifact)
    inquiry_tracker().record(
        InquiryRecord(
            inquiry_id=inquiry_id,
            client_inquiry_id=request.client_inquiry_id,
            client_id=credential.client_id,
            goal=request.goal,
            service_type=request.service_type,
            system_identifier=request.system_identifier,
            capability_id=artifact.qualified_id,
            reused_existing_capability=False,
            environment=request.environment,
        )
    )
    return DiscoverV1Response(
        capability_id=artifact.qualified_id,
        inquiry_id=inquiry_id,
        reused_existing_capability=False,
        lifecycle=artifact.lifecycle,
        approval_required=artifact.lifecycle not in AGENT_EXPOSABLE_LIFECYCLES,
    )


@router.post("/capabilities/{capability_id}/execute", response_model=ExecutionResult)
async def execute_v1(
    capability_id: str,
    request: ExecuteV1Request,
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> ExecutionResult:
    try:
        artifact = store().load(capability_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Capability not found") from exc
    if artifact.lifecycle not in AGENT_EXPOSABLE_LIFECYCLES:
        raise HTTPException(403, f"Capability '{capability_id}' is not approved for invocation")
    # A legacy artifact with no service_type predates this authorization model — allow any
    # authenticated + approved-lifecycle caller, identical to today's unauthenticated behavior,
    # just now requiring valid credentials. Known gap: backfill service_type onto such artifacts
    # to bring them fully under this model.
    if artifact.service_type is not None:
        require_service_type(artifact.service_type, credential)

    result = await replay_engine().execute(artifact, request.inputs)
    inquiry_tracker().record(
        InquiryRecord(
            inquiry_id=str(uuid4()),
            client_inquiry_id=request.client_inquiry_id,
            client_id=credential.client_id,
            service_type=artifact.service_type,
            system_identifier=artifact.system_identifier,
            capability_id=artifact.qualified_id,
            reused_existing_capability=True,
            status="executed",
        )
    )
    return result


@router.get("/capabilities/pending", response_model=PendingCapabilityListResponse)
def list_pending_capabilities_v1(
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> PendingCapabilityListResponse:
    if not credential.is_admin:
        raise HTTPException(403, "Client is not authorized to view the approval queue")
    drafts = [a for a in store().list() if a.lifecycle not in AGENT_EXPOSABLE_LIFECYCLES]
    return PendingCapabilityListResponse(
        capabilities=[
            PendingCapabilitySummary(
                capability_id=a.qualified_id,
                name=a.name,
                lifecycle=a.lifecycle,
                service_type=a.service_type,
                system_identifier=a.system_identifier,
                created_at=a.created_at,
                discovered_by=a.discovered_by,
            )
            for a in drafts
        ]
    )


@router.get("/capabilities/{capability_id}/review", response_model=CapabilityReviewResponse)
def review_capability_v1(
    capability_id: str,
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> CapabilityReviewResponse:
    if not credential.is_admin:
        raise HTTPException(403, "Client is not authorized to review capabilities")
    try:
        artifact = store().load(capability_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Capability not found") from exc
    # Every inquiry that ever asked for this exact capability_id, oldest first — not just the
    # one that triggered discovery, since a repeat caller's own inquiry is still worth showing
    # to a reviewer even though it didn't itself run discovery.
    inquiries = sorted(
        (i for i in inquiry_tracker().list() if i.capability_id == artifact.qualified_id),
        key=lambda i: i.created_at,
    )
    return CapabilityReviewResponse(
        capability_id=artifact.qualified_id,
        name=artifact.name,
        description=artifact.description,
        lifecycle=artifact.lifecycle,
        service_type=artifact.service_type,
        system_identifier=artifact.system_identifier,
        application=artifact.application,
        inputs=artifact.inputs,
        outputs=artifact.outputs,
        steps=artifact.steps,
        success=artifact.success,
        created_at=artifact.created_at,
        discovered_by=artifact.discovered_by,
        tags=artifact.tags,
        requested_by=[
            RequesterInfo(
                client_id=i.client_id,
                goal=i.goal,
                client_inquiry_id=i.client_inquiry_id,
                environment=i.environment,
                created_at=i.created_at,
            )
            for i in inquiries
        ],
    )


@router.post("/capabilities/{capability_id}/approve", response_model=ApproveV1Response)
def approve_v1(
    capability_id: str,
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> ApproveV1Response:
    if not credential.is_admin:
        raise HTTPException(403, "Client is not authorized to approve capabilities")
    try:
        artifact = store().load(capability_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Capability not found") from exc
    artifact.lifecycle = "approved"
    store().save(artifact)
    return ApproveV1Response(capability_id=artifact.qualified_id, lifecycle=artifact.lifecycle)
