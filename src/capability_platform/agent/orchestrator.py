"""Composes Layers 1-5: goal -> TaskIntent -> ExecutionPlan -> per-step CapabilityResolution ->
execution (deterministic replay, or a fallback to the existing ClaudeDiscoveryAgent) ->
deterministic aggregation -> grounded synthesis.

Never re-implements discovery or replay -- `discovery_agent_factory`/`executor` are the real,
unmodified `runtime.discovery_agent`/`CapabilityExecutor` (whose computer_use adapter itself
calls the real, unmodified `ReplayEngine`)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from capability_platform.agent.intent_analyzer import (
    ClarificationRequiredError,
    IntentAnalysisError,
    IntentAnalyzer,
)
from capability_platform.agent.models import (
    AgentResult,
    CapabilityExecutionResult,
    CapabilityResolution,
    ExecutionPlan,
    PlanStep,
    ResolutionType,
    TaskIntent,
)
from capability_platform.agent.plan_validator import PlanValidator
from capability_platform.agent.planner import Planner
from capability_platform.capabilities.executor import CapabilityExecutor
from capability_platform.capabilities.resolver import CapabilityResolver
from capability_platform.capabilities.store import AGENT_EXPOSABLE_LIFECYCLES, ArtifactStore
from capability_platform.models import (
    CapabilityArtifact,
    ErrorCategory,
    RiskLevel,
    RunError,
    RunStatus,
)
from capability_platform.observability.evidence import EvidenceCollector
from capability_platform.settings import settings
from capability_platform.synthesis.result import GroundedSynthesizer


class _DiscoveryAgent(Protocol):
    async def discover(
        self,
        goal: str,
        target_url: str,
        member_id: str = "10001",
        extra_known_values: dict[str, str] | None = None,
        system_identifier: str | None = None,
        run_id: str | None = None,
        capability_hint: str | None = None,
        name_hint: str | None = None,
        description_hint: str | None = None,
        output_type_hint: str | None = None,
        output_description_hint: str | None = None,
    ) -> CapabilityArtifact: ...


class AgentOrchestrator:
    def __init__(
        self,
        intent_analyzer: IntentAnalyzer,
        planner: Planner,
        plan_validator: PlanValidator,
        resolver: CapabilityResolver,
        executor: CapabilityExecutor,
        artifact_store: ArtifactStore,
        discovery_agent_factory: Callable[[], _DiscoveryAgent],
        evidence_root: Path,
        resolution_authorizer: Callable[[CapabilityResolution], None] | None = None,
    ) -> None:
        self.intent_analyzer = intent_analyzer
        self.planner = planner
        self.plan_validator = plan_validator
        self.resolver = resolver
        self.executor = executor
        self.artifact_store = artifact_store
        self.discovery_agent_factory = discovery_agent_factory
        self.evidence_root = evidence_root
        # Optional pre-execution authorization gate, called with each step's CapabilityResolution
        # right before it would be executed -- raise PermissionError to deny it. Lets a caller
        # (e.g. the REST layer, which knows the authenticated credential) enforce per-capability
        # scoping (such as require_service_type) without the orchestrator needing to know
        # anything about credentials or auth itself.
        self.resolution_authorizer = resolution_authorizer

    async def execute_goal(self, goal: str, context: dict[str, Any] | None = None) -> AgentResult:
        context = context or {}
        run_id = str(uuid4())
        evidence = EvidenceCollector(self.evidence_root, run_id)
        started_at = datetime.now(UTC)

        intent, plan, resolutions = await self._intent_plan_resolve(goal, context, evidence)

        execution: list[CapabilityExecutionResult] = []
        for step, resolution in zip(plan.steps, resolutions, strict=True):
            if resolution.resolution_type == ResolutionType.COMPUTER_USE_DISCOVERY:
                evidence.event(
                    "discovery.fallback_started", step_id=step.id, discovery_goal=resolution.discovery_goal
                )
                result = await self._run_discovery(step, resolution, intent, context)
            elif resolution.resolution_type == ResolutionType.UNRESOLVED:
                result = CapabilityExecutionResult(
                    step_id=step.id,
                    descriptor_id="",
                    status=RunStatus.FAILURE,
                    error=RunError(
                        category=ErrorCategory.INTERNAL,
                        code="UNRESOLVED_CAPABILITY",
                        message=resolution.reason,
                        step_id=step.id,
                        recoverable=False,
                    ),
                )
            elif (denial := self._authorization_denial(resolution)) is not None:
                result = CapabilityExecutionResult(
                    step_id=step.id,
                    descriptor_id=resolution.selected.descriptor.id if resolution.selected else "",
                    status=RunStatus.FAILURE,
                    error=RunError(
                        category=ErrorCategory.POLICY,
                        code="SERVICE_TYPE_NOT_AUTHORIZED",
                        message=denial,
                        step_id=step.id,
                        recoverable=False,
                    ),
                )
            else:
                inputs = self._collect_inputs(step, intent, context)
                result = await self.executor.execute(resolution, inputs)
            evidence.event(
                "capability.executed", step_id=step.id, descriptor_id=result.descriptor_id, status=str(result.status)
            )
            execution.append(result)

        outputs = self._aggregate(plan, execution)
        evidence.event("result.aggregated", outputs=outputs)
        status = self._overall_status(execution)
        business_code = self._first_business_code(execution)
        synthesized = GroundedSynthesizer.synthesize_agent_result(intent, outputs, status, business_code)
        evidence.event("result.synthesized", text=synthesized, status=str(status))

        return AgentResult(
            run_id=run_id,
            goal=goal,
            intent=intent,
            plan=plan,
            resolutions=resolutions,
            execution=execution,
            status=status,
            outputs=outputs,
            synthesized_text=synthesized,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    async def plan_only(
        self, goal: str, context: dict[str, Any] | None = None
    ) -> tuple[TaskIntent, ExecutionPlan, list[CapabilityResolution]]:
        context = context or {}
        run_id = str(uuid4())
        evidence = EvidenceCollector(self.evidence_root, run_id)
        return await self._intent_plan_resolve(goal, context, evidence)

    async def _intent_plan_resolve(
        self, goal: str, context: dict[str, Any], evidence: EvidenceCollector
    ) -> tuple[TaskIntent, ExecutionPlan, list[CapabilityResolution]]:
        try:
            intent = await self.intent_analyzer.analyze(goal, context, evidence)
        except IntentAnalysisError as exc:
            # Final safety net: an intent the analyzer couldn't even produce a valid TaskIntent
            # for routes straight to discovery with the raw goal, rather than failing the run.
            intent = TaskIntent(
                intent="unknown",
                domain="unknown",
                operation="read",
                risk=RiskLevel.READ_ONLY,
                confidence=0.0,
                raw_goal=goal,
                provider="none",
            )
            plan = ExecutionPlan(
                id=str(uuid4()),
                goal=goal,
                steps=[
                    PlanStep(
                        id="step-1",
                        description=goal,
                        operation="read",
                        risk=RiskLevel.READ_ONLY,
                        intent_ref="unknown",
                    )
                ],
            )
            resolution = CapabilityResolution(
                step_id="step-1",
                resolution_type=ResolutionType.COMPUTER_USE_DISCOVERY,
                reason=f"Intent analysis failed: {exc}",
                discovery_goal=goal,
            )
            evidence.event("plan.created", plan_id=plan.id, step_count=1, steps=["step-1"])
            evidence.event("plan.validated", steps_requiring_approval=[])
            return intent, plan, [resolution]

        if intent.requires_clarification:
            # The model itself flagged this goal as unclassifiable -- never guess at a plan for
            # it. Raised, not silently routed to discovery, since discovery would need a real
            # goal to attempt, and every field on this TaskIntent besides the clarification
            # question is an unusable placeholder (see the intent-analysis prompt's own
            # instruction on what to fill in when this flag is set).
            evidence.event("intent.clarification_required", question=intent.clarification_question)
            raise ClarificationRequiredError(intent.clarification_question)

        plan = self.planner.plan(intent)
        evidence.event(
            "plan.created", plan_id=plan.id, step_count=len(plan.steps), steps=[step.id for step in plan.steps]
        )
        known_inputs = {entity.name for entity in intent.entities} | set(context.keys())
        requires_approval = self.plan_validator.validate(plan, known_inputs=known_inputs)
        evidence.event("plan.validated", steps_requiring_approval=requires_approval)

        resolutions: list[CapabilityResolution] = []
        for step in plan.steps:
            resolution = self.resolver.resolve(step, context)
            candidate_ids = [candidate.descriptor.id for candidate in resolution.alternatives]
            if resolution.selected is not None:
                candidate_ids.append(resolution.selected.descriptor.id)
            evidence.event(
                "capability.candidates_retrieved",
                step_id=step.id,
                candidate_ids=candidate_ids,
                candidate_count=len(candidate_ids),
            )
            if resolution.selected is not None:
                evidence.event(
                    "capability.selected",
                    step_id=step.id,
                    descriptor_id=resolution.selected.descriptor.id,
                    resolution_type=str(resolution.resolution_type),
                    final_score=resolution.selected.final_score,
                )
            else:
                evidence.event(
                    "capability.rejected",
                    step_id=step.id,
                    reason=resolution.reason,
                    rejected_candidate_ids=[c.descriptor.id for c in resolution.alternatives],
                )
            resolutions.append(resolution)
        return intent, plan, resolutions

    async def _run_discovery(
        self, step: PlanStep, resolution: CapabilityResolution, intent: TaskIntent, context: dict[str, Any]
    ) -> CapabilityExecutionResult:
        agent = self.discovery_agent_factory()
        target_url = context.get("target_url", settings.target_url)
        member_id = intent.entity("memberId") or context.get("memberId", "10001")
        output_type_hint, output_description_hint = self._output_hint(step, intent)
        # intent.intent == "unknown" is the IntentAnalysisError sentinel (see
        # _intent_plan_resolve) -- there's nothing meaningful to hint from in that case, so fall
        # through to discover()'s own original hardcoded defaults rather than naming an artifact
        # "unknown".
        known_intent = intent.intent != "unknown"
        artifact = await agent.discover(
            resolution.discovery_goal or step.description,
            target_url,
            member_id,
            system_identifier=context.get("system_identifier"),
            capability_hint=intent.intent if known_intent else None,
            name_hint=intent.intent.replace("_", " ").title() if known_intent else None,
            description_hint=step.description if known_intent else None,
            output_type_hint=output_type_hint,
            output_description_hint=output_description_hint,
        )

        # Safety guard: ClaudeDiscoveryAgent's own artifact-id derivation can collide with an
        # already-approved capability's id (observed for real during Phase 8 -- a resolver miss
        # on a savings-balance-shaped goal triggered discovery, which then silently re-saved
        # lookup-member-savings-balance.v1 as a fresh draft). Never overwrite an
        # already-approved/active capability's id unless the caller explicitly opts in via
        # context={"force_rediscover": True} -- the same explicit-opt-in convention /v1/discover
        # already uses for intentional re-recording.
        existing = self._load_existing_artifact(artifact.qualified_id)
        if (
            existing is not None
            and existing.lifecycle in AGENT_EXPOSABLE_LIFECYCLES
            and not context.get("force_rediscover", False)
        ):
            return CapabilityExecutionResult(
                step_id=step.id,
                descriptor_id=artifact.qualified_id,
                status=RunStatus.FAILURE,
                error=RunError(
                    category=ErrorCategory.INTERNAL,
                    code="DISCOVERY_ID_COLLISION",
                    message=(
                        f"A newly discovered artifact would overwrite the already-"
                        f"{existing.lifecycle} capability '{artifact.qualified_id}'. Pass "
                        "context={'force_rediscover': True} to intentionally re-record it, or "
                        "supply a distinct system_identifier so discovery derives a different id."
                    ),
                    step_id=step.id,
                    recoverable=False,
                ),
            )

        # A freshly discovered artifact stays a draft -- identical to today's /v1/discover
        # behavior. The orchestrator never auto-approves it; approval gating is unchanged.
        self.artifact_store.save(artifact)
        return CapabilityExecutionResult(
            step_id=step.id,
            descriptor_id=artifact.qualified_id,
            status=RunStatus.PAUSED,
            raw_execution_result={"artifact_id": artifact.qualified_id, "lifecycle": artifact.lifecycle},
        )

    def _authorization_denial(self, resolution: CapabilityResolution) -> str | None:
        """None means allowed (no authorizer configured, or it raised nothing); a string is the
        denial reason. Only meaningful for resolutions the executor would otherwise run."""
        if self.resolution_authorizer is None:
            return None
        if resolution.resolution_type in (ResolutionType.COMPUTER_USE_DISCOVERY, ResolutionType.UNRESOLVED):
            return None
        try:
            self.resolution_authorizer(resolution)
        except PermissionError as exc:
            return str(exc)
        return None

    def _load_existing_artifact(self, qualified_id: str) -> CapabilityArtifact | None:
        try:
            return self.artifact_store.load(qualified_id)
        except FileNotFoundError:
            return None

    @staticmethod
    def _output_hint(step: PlanStep, intent: TaskIntent) -> tuple[str | None, str | None]:
        """Matches this step's first produced output against the TaskIntent's own
        required_outputs (by exact name) to steer discover()'s compiled OutputSpec type/
        description, instead of it always hardcoding type='number'/'Current savings balance'."""
        if not step.produced_outputs:
            return None, None
        target_name = step.produced_outputs[0]
        for output in intent.required_outputs:
            if output.name == target_name:
                return output.type, (output.description or None)
        return None, None

    @staticmethod
    def _collect_inputs(step: PlanStep, intent: TaskIntent, context: dict[str, Any]) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for name in step.required_inputs:
            value = intent.entity(name)
            if value is None:
                value = context.get(name)
            if value is not None:
                inputs[name] = value
        return inputs

    @staticmethod
    def _aggregate(plan: ExecutionPlan, execution: list[CapabilityExecutionResult]) -> dict[str, Any]:
        """Deterministic aggregation: exact-key dict lookups only. No LLM, no derivation."""
        results_by_step = {result.step_id: result for result in execution}
        outputs: dict[str, Any] = {}
        for step in plan.steps:
            result = results_by_step.get(step.id)
            if result is not None and result.status == RunStatus.SUCCESS:
                for name in step.produced_outputs:
                    if name in result.outputs:
                        outputs[name] = result.outputs[name]
        return outputs

    @staticmethod
    def _overall_status(execution: list[CapabilityExecutionResult]) -> RunStatus:
        if any(result.status == RunStatus.FAILURE for result in execution):
            return RunStatus.FAILURE
        if any(result.status == RunStatus.PAUSED for result in execution):
            return RunStatus.PAUSED
        if any(result.status == RunStatus.BUSINESS_OUTCOME for result in execution):
            return RunStatus.BUSINESS_OUTCOME
        return RunStatus.SUCCESS

    @staticmethod
    def _first_business_code(execution: list[CapabilityExecutionResult]) -> str | None:
        for result in execution:
            if result.business_code:
                return result.business_code
        return None
