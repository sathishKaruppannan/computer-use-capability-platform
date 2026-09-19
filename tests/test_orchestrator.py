from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_platform.agent.intent_analyzer import (
    ClarificationRequiredError,
    IntentAnalyzer,
    SensitiveInfoRequestedError,
)
from capability_platform.agent.orchestrator import AgentOrchestrator
from capability_platform.agent.plan_validator import PlanValidator
from capability_platform.agent.planner import Planner
from capability_platform.capabilities.executor import CapabilityExecutor
from capability_platform.capabilities.registry import CapabilityRegistry, build_registry
from capability_platform.capabilities.resolver import CapabilityResolver
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.llm.mock_provider import MockLLMProvider
from capability_platform.models import CapabilityArtifact, ExecutionResult, RunStatus
from capability_platform.policy.engine import PolicyEngine, default_policy
from capability_platform.settings import settings
from capability_platform.validation import GoalTooLongError

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
    resolution_authorizer=None,
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
        resolution_authorizer=resolution_authorizer,
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


async def test_discovery_failure_returns_a_clean_failure_result_not_an_unhandled_exception(tmp_path):
    """Regression test for a real bug found during live verification: a goal with no sensible
    business meaning on the target (e.g. 'Reticulate the splines for member 10001') drove
    discovery down a path where Claude tried to interact with an element that doesn't exist,
    raising a LookupError that propagated all the way to an unhandled 500. A goal this system
    genuinely can't fulfill must still be a clean, typed FAILURE -- never a crash."""

    class _FailingDiscoveryAgent:
        async def discover(self, goal, target_url, member_id="10001", **kwargs):
            raise LookupError("role:button matched 0")

    orchestrator = _build_orchestrator(
        tmp_path, lambda: _FailingDiscoveryAgent(), intent_response=OPEN_PREFERENCES_RESPONSE
    )
    result = await orchestrator.execute_goal(
        "Reticulate the splines for member 10001", context={"target_url": "http://127.0.0.1:8001"}
    )

    assert result.status == RunStatus.FAILURE
    assert result.execution[0].error.code == "DISCOVERY_FAILED"
    assert result.execution[0].error.category.value == "internal"
    # The raw Python exception class name is real, useful debug detail -- but not in the
    # human-readable `message` a chat UI shows verbatim (a real one, "(LookupError)", was found
    # showing up exactly there live). It lives in `observed` instead, alongside the full detail
    # already in this run's evidence trace.
    assert result.execution[0].error.observed == "LookupError"
    assert "LookupError" not in result.execution[0].error.message
    assert "role:button matched 0" not in result.execution[0].error.message


def _minimal_artifact(artifact_id: str, lifecycle: str) -> CapabilityArtifact:
    return CapabilityArtifact.model_validate(
        {
            "id": artifact_id,
            "version": 1,
            "name": artifact_id,
            "description": "test fixture",
            "lifecycle": lifecycle,
            "application": {
                "vendor": "Interface Demo",
                "product": "Legacy Member Servicing",
                "base_url": "http://127.0.0.1:8001",
            },
            "inputs": [],
            "outputs": [],
            "steps": [],
            "success": {"kind": "url"},
            "discovered_by": "mock:v1",
        }
    )


async def test_discovery_never_overwrites_an_already_approved_artifact(tmp_path):
    """Regression test for a real near-miss found during Phase 8: a freshly discovered artifact
    id colliding with an already-approved capability must never silently overwrite it."""
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_store.save(_minimal_artifact("colliding-capability", "approved"))

    class _CollidingDiscoveryAgent:
        async def discover(self, goal, target_url, member_id="10001", **kwargs):
            return _minimal_artifact("colliding-capability", "draft")

    empty_registry = CapabilityRegistry([])
    policy = PolicyEngine(default_policy())
    orchestrator = AgentOrchestrator(
        intent_analyzer=IntentAnalyzer(MockLLMProvider(OPEN_PREFERENCES_RESPONSE)),
        planner=Planner(),
        plan_validator=PlanValidator(policy),
        resolver=CapabilityResolver(empty_registry, artifact_store, policy),
        executor=CapabilityExecutor(artifact_store, lambda: _FakeReplayEngine(_fake_success_result())),
        artifact_store=artifact_store,
        discovery_agent_factory=lambda: _CollidingDiscoveryAgent(),
        evidence_root=tmp_path,
    )

    result = await orchestrator.execute_goal("some goal with no matching capability")

    assert result.status == RunStatus.FAILURE
    assert result.execution[0].error.code == "DISCOVERY_ID_COLLISION"
    # The on-disk artifact must be untouched -- still approved, not overwritten by the draft.
    reloaded = artifact_store.load("colliding-capability.v1")
    assert reloaded.lifecycle == "approved"


async def test_force_rediscover_allows_intentional_overwrite(tmp_path):
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_store.save(_minimal_artifact("colliding-capability", "approved"))

    class _CollidingDiscoveryAgent:
        async def discover(self, goal, target_url, member_id="10001", **kwargs):
            return _minimal_artifact("colliding-capability", "draft")

    empty_registry = CapabilityRegistry([])
    policy = PolicyEngine(default_policy())
    orchestrator = AgentOrchestrator(
        intent_analyzer=IntentAnalyzer(MockLLMProvider(OPEN_PREFERENCES_RESPONSE)),
        planner=Planner(),
        plan_validator=PlanValidator(policy),
        resolver=CapabilityResolver(empty_registry, artifact_store, policy),
        executor=CapabilityExecutor(artifact_store, lambda: _FakeReplayEngine(_fake_success_result())),
        artifact_store=artifact_store,
        discovery_agent_factory=lambda: _CollidingDiscoveryAgent(),
        evidence_root=tmp_path,
    )

    result = await orchestrator.execute_goal(
        "some goal with no matching capability", context={"force_rediscover": True}
    )

    assert result.execution[0].status == RunStatus.PAUSED
    reloaded = artifact_store.load("colliding-capability.v1")
    assert reloaded.lifecycle == "draft"


async def test_discovery_fallback_passes_intent_derived_hints(tmp_path):
    """Proves the orchestrator actually steers discover()'s artifact identity from the resolved
    TaskIntent/PlanStep, instead of leaving it to fall back to discover()'s own hardcoded
    savings-balance defaults for every goal regardless of what it actually was."""
    captured: dict = {}

    class _CapturingDiscoveryAgent:
        async def discover(self, goal, target_url, member_id="10001", **kwargs):
            captured.update(kwargs)
            return CapabilityArtifact.model_validate(
                {
                    "id": "open-account-preferences-page",
                    "version": 1,
                    "name": "stub",
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
        tmp_path, lambda: _CapturingDiscoveryAgent(), intent_response=OPEN_PREFERENCES_RESPONSE
    )
    await orchestrator.execute_goal(
        "Find member 10001 and open the account preferences page",
        context={"target_url": "http://127.0.0.1:8001"},
    )

    assert captured["capability_hint"] == "open_account_preferences_page"
    assert captured["name_hint"] == "Open Account Preferences Page"
    assert captured["output_type_hint"] == "string"


async def test_resolution_authorizer_denies_execution(tmp_path):
    def _deny(resolution):
        raise PermissionError("client is not authorized for this capability's service_type")

    def _discovery_agent_factory():
        raise AssertionError("a denied resolution must not fall through to discovery")

    orchestrator = _build_orchestrator(tmp_path, _discovery_agent_factory, resolution_authorizer=_deny)
    result = await orchestrator.execute_goal("Get the savings balance for member 10002")

    assert result.status == RunStatus.FAILURE
    assert result.execution[0].error.code == "SERVICE_TYPE_NOT_AUTHORIZED"
    assert result.execution[0].descriptor_id == "lookup-member-savings-balance.v1"


async def test_resolution_authorizer_allows_execution_when_it_raises_nothing(tmp_path):
    def _allow(resolution):
        return None

    def _discovery_agent_factory():
        raise AssertionError("must not reach discovery for a resolved capability")

    orchestrator = _build_orchestrator(tmp_path, _discovery_agent_factory, resolution_authorizer=_allow)
    result = await orchestrator.execute_goal("Get the savings balance for member 10002")

    assert result.status == RunStatus.SUCCESS
    assert result.outputs == {"savingsBalance": 1220.0}


AMBIGUOUS_GOAL_RESPONSE = {
    "intent": "unknown",
    "domain": "unknown",
    "operation": "read",
    "risk": "read_only",
    "confidence": 0.1,
    "requires_clarification": True,
    "clarification_question": "Which member, and what would you like to do for them?",
}


async def test_execute_goal_rejects_a_goal_over_the_length_limit_before_reaching_discovery(tmp_path):
    """The length check runs inside IntentAnalyzer.analyze() -- the very first thing the
    pipeline does -- so an over-length goal never reaches the resolver or discovery at all."""

    def _discovery_agent_factory():
        raise AssertionError("must never reach discovery for a goal that's too long")

    orchestrator = _build_orchestrator(tmp_path, _discovery_agent_factory)
    too_long_goal = "x" * (settings.max_goal_length + 1)
    with pytest.raises(GoalTooLongError):
        await orchestrator.execute_goal(too_long_goal)


async def test_plan_only_raises_clarification_required_for_ambiguous_goal(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("must never reach discovery for a goal needing clarification")

    orchestrator = _build_orchestrator(
        tmp_path, _discovery_agent_factory, intent_response=AMBIGUOUS_GOAL_RESPONSE
    )
    with pytest.raises(ClarificationRequiredError) as exc_info:
        await orchestrator.plan_only("Handle this member.")
    assert exc_info.value.question == "Which member, and what would you like to do for them?"


async def test_execute_goal_raises_clarification_required_and_never_executes(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("must never reach discovery for a goal needing clarification")

    orchestrator = _build_orchestrator(
        tmp_path, _discovery_agent_factory, intent_response=AMBIGUOUS_GOAL_RESPONSE
    )
    with pytest.raises(ClarificationRequiredError):
        await orchestrator.execute_goal("Handle this member.")


SENSITIVE_INFO_RESPONSE = {
    "intent": "unknown",
    "domain": "unknown",
    "operation": "read",
    "risk": "read_only",
    "confidence": 0.1,
    "requests_sensitive_info": True,
    "sensitive_info_reason": "Full SSNs are not provided through this system",
}


async def test_execute_goal_refuses_a_sensitive_info_request_before_planning(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("must never reach discovery for a refused sensitive-info request")

    orchestrator = _build_orchestrator(
        tmp_path, _discovery_agent_factory, intent_response=SENSITIVE_INFO_RESPONSE
    )
    with pytest.raises(SensitiveInfoRequestedError) as exc_info:
        await orchestrator.execute_goal("What is member 10002's full Social Security Number?")
    assert exc_info.value.reason == "Full SSNs are not provided through this system"


async def test_plan_only_refuses_a_sensitive_info_request(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("must never reach discovery for a refused sensitive-info request")

    orchestrator = _build_orchestrator(
        tmp_path, _discovery_agent_factory, intent_response=SENSITIVE_INFO_RESPONSE
    )
    with pytest.raises(SensitiveInfoRequestedError):
        await orchestrator.plan_only("What is member 10002's full Social Security Number?")


CONVERSATIONAL_RESPONSE = {
    "intent": "unknown",
    "domain": "unknown",
    "operation": "read",
    "risk": "read_only",
    "confidence": 0.1,
    "is_conversational": True,
    "conversational_reply": "You're welcome! Let me know if there's anything else I can help with.",
}


async def test_execute_goal_returns_conversational_reply_without_planning_or_resolving(tmp_path):
    """Regression test for a real bug found live: a pure acknowledgment ('thank you') was being
    misclassified through the ambiguous-goal guardrail and surfaced as a 'Clarification required'
    error bubble. It must instead resolve to a plain, successful conversational reply with zero
    steps planned, zero capabilities resolved, and zero discovery attempted."""

    def _discovery_agent_factory():
        raise AssertionError("a conversational message must never reach discovery")

    orchestrator = _build_orchestrator(
        tmp_path, _discovery_agent_factory, intent_response=CONVERSATIONAL_RESPONSE
    )
    result = await orchestrator.execute_goal("Thank you, that's all I needed.")

    assert result.status == RunStatus.SUCCESS
    assert result.plan.steps == []
    assert result.resolutions == []
    assert result.execution == []
    assert result.outputs == {}
    assert result.synthesized_text == "You're welcome! Let me know if there's anything else I can help with."


async def test_plan_only_returns_empty_plan_for_a_conversational_message(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("a conversational message must never reach discovery")

    orchestrator = _build_orchestrator(
        tmp_path, _discovery_agent_factory, intent_response=CONVERSATIONAL_RESPONSE
    )
    intent, plan, resolutions = await orchestrator.plan_only("No, I am good.")

    assert intent.is_conversational is True
    assert plan.steps == []
    assert resolutions == []


async def test_plan_only_does_not_execute_anything(tmp_path):
    def _discovery_agent_factory():
        raise AssertionError("plan_only must never invoke discovery")

    orchestrator = _build_orchestrator(tmp_path, _discovery_agent_factory)
    intent, plan, resolutions = await orchestrator.plan_only("Get the savings balance for member 10002")

    assert intent.intent == "retrieve_account_balance"
    assert len(plan.steps) == 1
    assert resolutions[0].selected.descriptor.id == "lookup-member-savings-balance.v1"
