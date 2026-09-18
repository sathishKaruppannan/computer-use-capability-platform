from datetime import UTC, datetime
from pathlib import Path

from capability_platform.agent.intent_analyzer import IntentAnalyzer
from capability_platform.agent.orchestrator import AgentOrchestrator
from capability_platform.agent.plan_validator import PlanValidator
from capability_platform.agent.planner import Planner
from capability_platform.capabilities.executor import CapabilityExecutor
from capability_platform.capabilities.registry import build_registry
from capability_platform.capabilities.resolver import CapabilityResolver
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.llm.mock_provider import MockLLMProvider
from capability_platform.models import CapabilityArtifact, ExecutionResult, RunStatus
from capability_platform.policy.engine import PolicyEngine, default_policy

SAVINGS_BALANCE_RESPONSE = {
    "intent": "retrieve_account_balance",
    "domain": "member_servicing",
    "operation": "read",
    "entities": [
        {"name": "memberId", "value": "10002", "type": "string"},
        {"name": "accountType", "value": "savings", "type": "string"},
    ],
    "required_outputs": [{"name": "savingsBalance", "type": "number"}],
    "risk": "read_only",
    "confidence": 0.95,
}

OPEN_PREFERENCES_RESPONSE = {
    "intent": "open_account_preferences_page",
    "domain": "member_servicing",
    "operation": "read",
    "entities": [{"name": "memberId", "value": "10001", "type": "string"}],
    "required_outputs": [{"name": "confirmation", "type": "string"}],
    "risk": "read_only",
    "confidence": 0.8,
}


class _FakeReplayEngine:
    def __init__(self, result: ExecutionResult) -> None:
        self._result = result

    async def execute(self, artifact, inputs) -> ExecutionResult:
        return self._result


def _fake_success_result() -> ExecutionResult:
    now = datetime.now(UTC)
    return ExecutionResult(
        run_id="fake-run",
        status=RunStatus.SUCCESS,
        capability_id="lookup-member-savings-balance.v1",
        outputs={"savingsBalance": 1220.0},
        started_at=now,
        completed_at=now,
    )


def _build_orchestrator(
    tmp_path: Path,
    discovery_agent_factory,
    fake_result: ExecutionResult | None = None,
    intent_response: dict | None = None,
):
    artifact_store = ArtifactStore(Path("artifacts"))
    registry = build_registry(artifact_store)
    policy = PolicyEngine(default_policy())
    resolver = CapabilityResolver(registry, artifact_store, policy)
    executor = CapabilityExecutor(
        artifact_store, lambda: _FakeReplayEngine(fake_result or _fake_success_result())
    )
    return AgentOrchestrator(
        intent_analyzer=IntentAnalyzer(MockLLMProvider(intent_response or SAVINGS_BALANCE_RESPONSE)),
        planner=Planner(),
        plan_validator=PlanValidator(policy),
        resolver=resolver,
        executor=executor,
        artifact_store=artifact_store,
        discovery_agent_factory=discovery_agent_factory,
        evidence_root=tmp_path,
    )


async def test_existing_capability_prevents_new_discovery(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("discovery must not be invoked when an existing capability resolves")

    orchestrator = _build_orchestrator(tmp_path, _discovery_agent_factory)
    result = await orchestrator.execute_goal("Get the savings balance for member 10002")

    assert result.status == RunStatus.SUCCESS
    assert result.outputs == {"savingsBalance": 1220.0}
    assert result.execution[0].descriptor_id == "lookup-member-savings-balance.v1"
    assert result.resolutions[0].resolution_type.value == "computer_use_capability"


async def test_unresolved_step_falls_back_to_real_discovery_agent(tmp_path):
    calls: list[str] = []

    class _StubDiscoveryAgent:
        async def discover(self, goal, target_url, member_id="10001", **kwargs):
            calls.append(goal)
            return CapabilityArtifact.model_validate(
                {
                    "id": "open-account-preferences",
                    "version": 1,
                    "name": "Open account preferences",
                    "description": "stub",
                    "application": {
                        "vendor": "Interface Demo",
                        "product": "Legacy Member Servicing",
                        "base_url": target_url,
                    },
                    "inputs": [],
                    "outputs": [],
                    "steps": [],
                    "success": {"kind": "url"},
                    "discovered_by": "mock:v1",
                }
            )

    orchestrator = _build_orchestrator(
        tmp_path, lambda: _StubDiscoveryAgent(), intent_response=OPEN_PREFERENCES_RESPONSE
    )
    result = await orchestrator.execute_goal(
        "Find member 10001 and open the account preferences page",
        context={"target_url": "http://127.0.0.1:8001"},
    )

    assert calls, "discovery agent should have been invoked for an unresolvable step"
    assert result.status == RunStatus.PAUSED
    assert result.execution[0].descriptor_id == "open-account-preferences.v1"


async def test_plan_only_does_not_execute_anything(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("plan_only must never invoke discovery")

    orchestrator = _build_orchestrator(tmp_path, _discovery_agent_factory)
    intent, plan, resolutions = await orchestrator.plan_only("Get the savings balance for member 10002")

    assert intent.intent == "retrieve_account_balance"
    assert len(plan.steps) == 1
    assert resolutions[0].selected.descriptor.id == "lookup-member-savings-balance.v1"
