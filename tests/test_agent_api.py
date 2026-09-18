"""REST-level coverage for POST /agent/execute's per-capability require_service_type
authorization gate -- proves the real wiring in api/agent_routes.py, not just the orchestrator-
level mechanism (already covered directly in test_orchestrator.py). No live Claude/browser call:
the fake orchestrator factory below swaps in a MockLLMProvider-backed IntentAnalyzer and a fake
ReplayEngine, but keeps the real _require_service_type_authorizer logic from api/agent_routes.py
in the loop -- only the LLM/browser edges are faked, not the authorization decision itself."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from capability_platform.access.credentials import JSONCredentialStore, hash_password
from capability_platform.access.models import ClientCredential
from capability_platform.agent.intent_analyzer import IntentAnalyzer
from capability_platform.agent.orchestrator import AgentOrchestrator
from capability_platform.agent.plan_validator import PlanValidator
from capability_platform.agent.planner import Planner
from capability_platform.api import agent_routes as agent_routes_module
from capability_platform.api import app as app_module
from capability_platform.capabilities.executor import CapabilityExecutor
from capability_platform.capabilities.registry import build_registry
from capability_platform.capabilities.resolver import CapabilityResolver
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.llm.mock_provider import MockLLMProvider
from capability_platform.models import (
    ApplicationBinding,
    CapabilityArtifact,
    Checkpoint,
    ExecutionResult,
    Locator,
    OutputSpec,
    ParameterSpec,
    RunStatus,
    ServiceType,
    Target,
)
from capability_platform.policy.engine import PolicyEngine, default_policy
from capability_platform.settings import settings as global_settings

SAVINGS_BALANCE_RESPONSE = {
    "intent": "retrieve_account_balance",
    "domain": "member_servicing",
    "operation": "read",
    "entities": [{"name": "memberId", "value": "10002", "type": "string"}],
    "required_outputs": [{"name": "savingsBalance", "type": "number"}],
    "risk": "read_only",
    "confidence": 0.95,
}


class _FakeReplayEngine:
    async def execute(self, artifact, inputs):
        now = datetime.now(UTC)
        return ExecutionResult(
            run_id="fake-run",
            status=RunStatus.SUCCESS,
            capability_id=artifact.qualified_id,
            outputs={"savingsBalance": 1220.0},
            started_at=now,
            completed_at=now,
        )


def _artifact(id_: str, service_type: ServiceType | None) -> CapabilityArtifact:
    return CapabilityArtifact(
        id=id_,
        name="Lookup member savings balance",
        description="test fixture",
        lifecycle="approved",
        application=ApplicationBinding(
            vendor="Interface Demo", product="Legacy Member Servicing", base_url="http://127.0.0.1:8001"
        ),
        inputs=[ParameterSpec(name="memberId", type="string", description="x")],
        outputs=[OutputSpec(name="savingsBalance", type="number", description="x")],
        steps=[],
        success=Checkpoint(
            kind="visible", target=Target(primary=Locator(strategy="text", value="x"), rationale="x")
        ),
        discovered_by="test",
        service_type=service_type,
    )


def _configure(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "artifact_dir", tmp_path / "artifacts")
    monkeypatch.setattr(global_settings, "credential_dir", tmp_path / "credentials")
    monkeypatch.setattr(global_settings, "evidence_dir", tmp_path / "evidence")


def _register_client(client_id: str, password: str, service_types: list[ServiceType]) -> None:
    password_hash, password_salt = hash_password(password)
    JSONCredentialStore(global_settings.credential_dir).save(
        ClientCredential(
            client_id=client_id,
            password_hash=password_hash,
            password_salt=password_salt,
            authorized_service_types=service_types,
        )
    )


def _install_fake_orchestrator(monkeypatch, intent_response=None):
    def _factory(environment="production", resolution_authorizer=None):
        artifact_store = ArtifactStore(global_settings.artifact_dir)
        registry = build_registry(artifact_store)
        policy = PolicyEngine(default_policy())
        return AgentOrchestrator(
            intent_analyzer=IntentAnalyzer(MockLLMProvider(intent_response or SAVINGS_BALANCE_RESPONSE)),
            planner=Planner(),
            plan_validator=PlanValidator(policy),
            resolver=CapabilityResolver(registry, artifact_store, policy),
            executor=CapabilityExecutor(artifact_store, lambda: _FakeReplayEngine()),
            artifact_store=artifact_store,
            discovery_agent_factory=lambda: (_ for _ in ()).throw(
                AssertionError("no discovery expected in this test")
            ),
            evidence_root=global_settings.evidence_dir,
            resolution_authorizer=resolution_authorizer,
        )

    monkeypatch.setattr(agent_routes_module, "agent_orchestrator", _factory)


def test_execute_agent_requires_authentication(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app_module.app)
    response = client.post(
        "/agent/execute", json={"goal": "irrelevant", "client_inquiry_id": "req-1"}
    )
    assert response.status_code == 401


def test_execute_agent_rejects_capability_service_type_not_authorized(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [])  # authorized for nothing
    ArtifactStore(global_settings.artifact_dir).save(
        _artifact("lookup-member-savings-balance", ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP)
    )
    _install_fake_orchestrator(monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/agent/execute",
        json={"goal": "Get the savings balance for member 10002", "client_inquiry_id": "req-1"},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] == "failure"
    assert body["execution"][0]["error"]["code"] == "SERVICE_TYPE_NOT_AUTHORIZED"


def test_execute_agent_allows_authorized_service_type(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    ArtifactStore(global_settings.artifact_dir).save(
        _artifact("lookup-member-savings-balance", ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP)
    )
    _install_fake_orchestrator(monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/agent/execute",
        json={"goal": "Get the savings balance for member 10002", "client_inquiry_id": "req-1"},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] == "success"
    assert body["result"]["outputs"] == {"savingsBalance": 1220.0}


def test_execute_agent_allows_unscoped_capability_regardless_of_service_type(monkeypatch, tmp_path):
    """A legacy/unscoped capability (service_type=None) is invocable by any authenticated
    caller -- same convention as api/v1_routes.py::execute_v1 for a legacy artifact."""
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [])  # authorized for nothing
    ArtifactStore(global_settings.artifact_dir).save(
        _artifact("lookup-member-savings-balance", service_type=None)
    )
    _install_fake_orchestrator(monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/agent/execute",
        json={"goal": "Get the savings balance for member 10002", "client_inquiry_id": "req-1"},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "success"


UNSATISFIABLE_SUB_GOAL_RESPONSE = {
    "intent": "retrieve_balance_and_create_note",
    "domain": "member_servicing",
    "operation": "write",
    "entities": [{"name": "memberId", "value": "10001", "type": "string"}],
    "required_outputs": [{"name": "noteId", "type": "string"}],
    "risk": "reversible",
    "confidence": 0.85,
    "sub_goals": [
        {
            "description": "Create a servicing note on the member's account.",
            "operation": "write",
            "required_inputs": ["memberId", "note"],
            "produced_outputs": ["noteId"],
        }
    ],
}


def test_plan_agent_returns_400_on_unsatisfiable_plan(monkeypatch, tmp_path):
    """Regression test: a real live run during Phase 10 crashed the CLI with a raw traceback
    when a plan step needed an input the goal never supplied ('note' content). Both /agent/plan
    and /agent/execute must surface this as a clean 400, not an unhandled exception."""
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _install_fake_orchestrator(monkeypatch, intent_response=UNSATISFIABLE_SUB_GOAL_RESPONSE)
    client = TestClient(app_module.app)

    response = client.post(
        "/agent/plan",
        json={"goal": "Create a servicing note for member 10001"},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 400
    assert "missing required inputs" in response.json()["detail"]


def test_execute_agent_returns_400_on_unsatisfiable_plan(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _install_fake_orchestrator(monkeypatch, intent_response=UNSATISFIABLE_SUB_GOAL_RESPONSE)
    client = TestClient(app_module.app)

    response = client.post(
        "/agent/execute",
        json={"goal": "Create a servicing note for member 10001", "client_inquiry_id": "req-1"},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 400


AMBIGUOUS_GOAL_RESPONSE = {
    "intent": "unknown",
    "domain": "unknown",
    "operation": "read",
    "risk": "read_only",
    "confidence": 0.1,
    "requires_clarification": True,
    "clarification_question": "Which member, and what would you like to do for them?",
}


def test_plan_agent_returns_400_with_clarification_question_for_ambiguous_goal(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _install_fake_orchestrator(monkeypatch, intent_response=AMBIGUOUS_GOAL_RESPONSE)
    client = TestClient(app_module.app)

    response = client.post(
        "/agent/plan",
        json={"goal": "Handle this member."},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 400
    assert "Which member, and what would you like to do for them?" in response.json()["detail"]


def test_execute_agent_returns_400_with_clarification_question_for_ambiguous_goal(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _install_fake_orchestrator(monkeypatch, intent_response=AMBIGUOUS_GOAL_RESPONSE)
    client = TestClient(app_module.app)

    response = client.post(
        "/agent/execute",
        json={"goal": "Handle this member.", "client_inquiry_id": "req-1"},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 400
    assert "Which member, and what would you like to do for them?" in response.json()["detail"]
