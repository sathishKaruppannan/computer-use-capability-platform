"""POST /agent/execute and POST /agent/plan -- the natural-language entry points that route a
goal through intent analysis, planning, and capability resolution before any computer-use
discovery is considered. Authenticated the same way as /v1/* (never the unauthenticated legacy
surface): /agent/execute can trigger live discovery, the same cost/side-effect profile as
/v1/discover.

Known simplification: per-capability require_service_type scoping is not applied here, unlike
/v1/capabilities/{id}/execute -- the orchestrator can resolve to any capability dynamically,
not a single known id, so there is no single service_type to check up front."""

from fastapi import APIRouter, Depends

from capability_platform.access.models import ClientCredential
from capability_platform.api.auth import authenticate_client
from capability_platform.api.schemas.requests import AgentExecuteRequest, AgentPlanRequest
from capability_platform.api.schemas.responses import (
    AgentExecuteResponse,
    AgentPlanResponse,
    AgentResultSummary,
)
from capability_platform.runtime import agent_orchestrator

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/execute", response_model=AgentExecuteResponse)
async def execute_agent(
    request: AgentExecuteRequest,
    credential: ClientCredential = Depends(authenticate_client),  # noqa: B008 - FastAPI's own idiom
) -> AgentExecuteResponse:
    del credential  # authentication only; no per-capability scoping check here, see module docstring
    result = await agent_orchestrator().execute_goal(request.goal, request.context)
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
    intent, plan, resolutions = await agent_orchestrator().plan_only(request.goal, request.context)
    return AgentPlanResponse(run_id=plan.id, intent=intent, plan=plan, resolutions=resolutions)
