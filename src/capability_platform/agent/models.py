"""Goal-orchestration domain models: NL goal -> TaskIntent -> ExecutionPlan ->
CapabilityResolution -> execution -> AgentResult.

Deliberately separate from `capability_platform.models` (the artifact/replay domain that
`ReplayEngine` and the `/v1` DTOs depend on) so that module's import surface -- and therefore
`computer_use/replay.py`'s transitive dependency graph -- stays exactly as small as it is today.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from capability_platform.models import CapabilityDescriptor, RiskLevel, RunError, RunStatus


class ExtractedEntity(BaseModel):
    name: str
    value: str
    type: Literal["string", "integer", "number", "boolean"] = "string"
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_span: str | None = Field(
        default=None, description="Substring of the raw goal this entity was extracted from, for audit."
    )


class RequiredOutput(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean", "object"] = "string"
    description: str = ""


class SubGoal(BaseModel):
    """One ordered piece of a compound goal ('find member, get balance, create a note'), as
    identified by the Intent Analyzer's own LLM call. The Planner turns each of these directly
    into a PlanStep with sequential dependencies -- it never decomposes a compound goal itself
    (the Planner stays deterministic, no LLM call of its own); this is how that intelligence
    reaches it without adding a second LLM call anywhere in the pipeline."""

    description: str
    operation: Literal["read", "write"]
    required_inputs: list[str] = Field(default_factory=list)
    produced_outputs: list[str] = Field(default_factory=list)


class TaskIntent(BaseModel):
    """Never executes anything -- the Intent Analyzer's sole output. Layer 1 of the pipeline."""

    intent: str = Field(description="Stable snake_case intent id, e.g. 'retrieve_account_balance'.")
    domain: str = Field(description="Business domain, e.g. 'member_servicing'.")
    operation: Literal["read", "write"]
    entities: list[ExtractedEntity] = Field(default_factory=list)
    required_outputs: list[RequiredOutput] = Field(default_factory=list)
    risk: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    missing_required_inputs: list[str] = Field(default_factory=list)
    sub_goals: list[SubGoal] = Field(
        default_factory=list,
        description="Populated only for a compound goal describing multiple distinct actions in "
        "sequence. Empty for a single-action goal -- the Planner's existing template/generic-step "
        "logic handles that case unchanged.",
    )
    raw_goal: str
    provider: str = Field(description="Provenance tag of the LLM provider that produced this, e.g. 'mock:v1'.")

    def entity(self, name: str) -> str | None:
        return next((e.value for e in self.entities if e.name == name), None)


class PlanStep(BaseModel):
    """One step of an ExecutionPlan. `required_inputs`/`produced_outputs` are strictly the
    capability's EXECUTION contract -- not every TaskIntent entity belongs here (see Planner)."""

    id: str
    description: str
    operation: Literal["read", "write"]
    required_inputs: list[str] = Field(default_factory=list)
    produced_outputs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    risk: RiskLevel
    intent_ref: str = Field(description="TaskIntent.intent this step serves.")


class ExecutionPlan(BaseModel):
    id: str
    goal: str
    steps: list[PlanStep]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    planner: str = "planner:v1"


class ResolutionType(StrEnum):
    API = "api"
    LOCAL_TOOL = "local_tool"
    MCP_TOOL = "mcp_tool"
    SKILL = "skill"
    COMPUTER_USE_CAPABILITY = "computer_use_capability"
    COMPUTER_USE_DISCOVERY = "computer_use_discovery"
    UNRESOLVED = "unresolved"


class CapabilityCandidate(BaseModel):
    descriptor: CapabilityDescriptor
    semantic_score: float
    input_compatible: bool
    output_compatible: bool
    trust_ok: bool
    policy_ok: bool
    tenant_ok: bool
    reliability: float
    final_score: float
    rejection_reasons: list[str] = Field(default_factory=list)


class CapabilityResolution(BaseModel):
    step_id: str
    resolution_type: ResolutionType
    selected: CapabilityCandidate | None = None
    alternatives: list[CapabilityCandidate] = Field(default_factory=list)
    reason: str
    discovery_goal: str | None = Field(
        default=None, description="Set only when resolution_type == COMPUTER_USE_DISCOVERY."
    )


class CapabilityExecutionRequest(BaseModel):
    step_id: str
    descriptor_id: str
    source: Literal["local_tool", "mcp_tool", "skill", "computer_use", "api"]
    inputs: dict[str, Any]


class CapabilityExecutionResult(BaseModel):
    step_id: str
    descriptor_id: str
    status: RunStatus
    outputs: dict[str, Any] = Field(default_factory=dict)
    business_code: str | None = None
    error: RunError | None = None
    raw_execution_result: dict[str, Any] | None = Field(
        default=None, description="ExecutionResult.model_dump() when source == 'computer_use'."
    )


class AgentResult(BaseModel):
    """AgentOrchestrator.execute_goal's return type."""

    run_id: str
    goal: str
    intent: TaskIntent
    plan: ExecutionPlan
    resolutions: list[CapabilityResolution]
    execution: list[CapabilityExecutionResult]
    status: RunStatus
    outputs: dict[str, Any] = Field(default_factory=dict)
    synthesized_text: str
    started_at: datetime
    completed_at: datetime | None = None
