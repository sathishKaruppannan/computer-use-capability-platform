"""Layer 4: normalizes execution across capability sources. A dispatch table keyed by
`descriptor.source` -- the "executor adapter" CLAUDE.md calls for when a new capability source
is added: this is the one place that dispatches by source, downstream code never branches on it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from capability_platform.agent.models import CapabilityExecutionResult, CapabilityResolution
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.models import ErrorCategory, RunError, RunStatus
from capability_platform.skills.member_financial_summary import (
    CapabilityInvoker,
    MemberFinancialSummarySkill,
)


class CapabilityExecutor:
    def __init__(
        self, artifact_store: ArtifactStore, replay_engine_factory: Callable[[], ReplayEngine]
    ) -> None:
        self.artifact_store = artifact_store
        self.replay_engine_factory = replay_engine_factory

    async def execute(
        self, resolution: CapabilityResolution, inputs: dict[str, Any]
    ) -> CapabilityExecutionResult:
        if resolution.selected is None:
            raise ValueError(
                f"Cannot execute resolution for step '{resolution.step_id}': no candidate was selected"
            )
        descriptor = resolution.selected.descriptor
        adapter = self._ADAPTERS.get(descriptor.source)
        if adapter is None:
            raise NotImplementedError(f"no executor adapter registered for source={descriptor.source!r}")
        return await adapter(self, descriptor.id, inputs, resolution.step_id)

    async def _execute_computer_use(
        self, descriptor_id: str, inputs: dict[str, Any], step_id: str
    ) -> CapabilityExecutionResult:
        artifact = self.artifact_store.load(descriptor_id)
        result = await self.replay_engine_factory().execute(artifact, inputs)
        return CapabilityExecutionResult(
            step_id=step_id,
            descriptor_id=descriptor_id,
            status=result.status,
            outputs=result.outputs,
            business_code=result.business_code,
            error=result.error,
            raw_execution_result=result.model_dump(mode="json"),
        )

    async def _execute_skill(
        self, descriptor_id: str, inputs: dict[str, Any], step_id: str
    ) -> CapabilityExecutionResult:
        invoker = _ReplayCapabilityInvoker(self.artifact_store, self.replay_engine_factory)
        skill = MemberFinancialSummarySkill(invoker)
        member_id = inputs.get("memberId")
        if member_id is None:
            return CapabilityExecutionResult(
                step_id=step_id,
                descriptor_id=descriptor_id,
                status=RunStatus.FAILURE,
                error=_missing_input_error(step_id, "memberId"),
            )
        outputs = await skill.execute(member_id)
        return CapabilityExecutionResult(
            step_id=step_id, descriptor_id=descriptor_id, status=RunStatus.SUCCESS, outputs=outputs
        )

    async def _execute_unimplemented(
        self, descriptor_id: str, inputs: dict[str, Any], step_id: str
    ) -> CapabilityExecutionResult:
        raise NotImplementedError(f"no executor adapter registered for descriptor={descriptor_id!r}")

    _ADAPTERS: ClassVar[
        dict[str, Callable[[CapabilityExecutor, str, dict[str, Any], str], Awaitable[CapabilityExecutionResult]]]
    ] = {
        "computer_use": _execute_computer_use,
        "skill": _execute_skill,
        "local_tool": _execute_unimplemented,
        "mcp_tool": _execute_unimplemented,
        "api": _execute_unimplemented,
    }


class _ReplayCapabilityInvoker(CapabilityInvoker):
    """Adapts ReplayEngine to the CapabilityInvoker protocol a skill expects, so
    MemberFinancialSummarySkill can call the real, unmodified replay engine without knowing it."""

    def __init__(self, artifact_store: ArtifactStore, replay_engine_factory: Callable[[], ReplayEngine]) -> None:
        self.artifact_store = artifact_store
        self.replay_engine_factory = replay_engine_factory

    async def invoke(self, capability_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        artifact = self.artifact_store.load(capability_id)
        result = await self.replay_engine_factory().execute(artifact, inputs)
        return result.model_dump(mode="json")


def _missing_input_error(step_id: str, name: str) -> RunError:
    return RunError(
        category=ErrorCategory.VALIDATION,
        code="MISSING_INPUT",
        message=f"Missing required input '{name}'",
        step_id=step_id,
        recoverable=False,
    )
