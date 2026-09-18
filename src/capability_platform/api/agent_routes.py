"""POST /agent/execute and POST /agent/plan -- the natural-language entry points that route a
goal through intent analysis, planning, and capability resolution before any computer-use
discovery is considered. Authenticated the same way as /v1/* (never the unauthenticated legacy
surface): /agent/execute can trigger live discovery, the same cost/side-effect profile as
/v1/discover.

/agent/execute enforces the same require_service_type scoping /v1/capabilities/{id}/execute
does, just resolved per-step after capability resolution rather than known up front from the
request -- the orchestrator can resolve to any capability dynamically, so there is no single
service_type to check before resolving. A capability with no service_type (legacy/unscoped, same
convention as api/v1_routes.py::execute_v1) is invocable by any authenticated caller."""

from fastapi import APIRouter, Depends, HTTPException

from capability_platform.access.models import ClientCredential
from capability_platform.agent.intent_analyzer import ClarificationRequiredError
from capability_platform.agent.models import CapabilityResolution
from capability_platform.agent.plan_validator import PlanValidationError
from capability_platform.api.auth import authenticate_client
from capability_platform.api.schemas.requests import AgentExecuteRequest, AgentPlanRequest
from capability_platform.api.schemas.responses import (
    AgentExecuteResponse,
    AgentPlanResponse,
    AgentResultSummary,
)
from capability_platform.runtime import agent_orchestrator

router = APIRouter(prefix="/agent", tags=["agent"])


def _require_service_type_authorizer(credential: ClientCredential):
    def _authorize(resolution: CapabilityResolution) -> None:
        descriptor = resolution.selected.descriptor if resolution.selected else None
        service_type = descriptor.service_type if descriptor else None
        if service_type is not None and service_type not in credential.authorized_service_types:
            raise PermissionError(
                f"Client '{credential.client_id}' is not authorized for service_type={service_type}"
            )

    return _authorize


@router.post("/execute", response_model=AgentExecuteResponse)
async def execute_agent(
    request: AgentExecuteRequest,
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> AgentExecuteResponse:
    orchestrator = agent_orchestrator(resolution_authorizer=_require_service_type_authorizer(credential))
    try:
        result = await orchestrator.execute_goal(request.goal, request.context)
    except ClarificationRequiredError as exc:
        raise HTTPException(400, f"Clarification required: {exc.question}") from exc
    except PlanValidationError as exc:
        raise HTTPException(400, f"Plan validation failed: {exc}") from exc
    return AgentExecuteResponse(
        run_id=result.run_id,
        intent=result.intent,
        plan=result.plan,
        resolutions=result.resolutions,
        execution=result.execution,
        result=AgentResultSummary(
            status=result.status,
            outputs=result.outputs,
            business_code=next((r.business_code for r in result.execution if r.business_code), None),
            synthesized_text=result.synthesized_text,
        ),
    )


@router.post("/plan", response_model=AgentPlanResponse)
async def plan_agent(
    request: AgentPlanRequest,
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> AgentPlanResponse:
    del credential
    try:
        intent, plan, resolutions = await agent_orchestrator().plan_only(request.goal, request.context)
    except ClarificationRequiredError as exc:
        raise HTTPException(400, f"Clarification required: {exc.question}") from exc
    except PlanValidationError as exc:
        raise HTTPException(400, f"Plan validation failed: {exc}") from exc
    return AgentPlanResponse(run_id=plan.id, intent=intent, plan=plan, resolutions=resolutions)
