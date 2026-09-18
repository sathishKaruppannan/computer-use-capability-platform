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

from capability_platform.agent.intent_analyzer import IntentAnalysisError, IntentAnalyzer
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
from capability_platform.capabilities.store import ArtifactStore
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
    ) -> None:
        self.intent_analyzer = intent_analyzer
        self.planner = planner
        self.plan_validator = plan_validator
        self.resolver = resolver
        self.executor = executor
        self.artifact_store = artifact_store
        self.discovery_agent_factory = discovery_agent_factory
        self.evidence_root = evidence_root

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
        artifact = await agent.discover(
            resolution.discovery_goal or step.description,
            target_url,
            member_id,
            system_identifier=context.get("system_identifier"),
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
