from datetime import UTC, datetime
from pathlib import Path

import pytest

from capability_platform.access.models import TenantCredential
from capability_platform.access.tenant_credentials import JSONTenantCredentialStore
from capability_platform.agent.models import (
    CapabilityCandidate,
    CapabilityResolution,
    ResolutionType,
)
from capability_platform.capabilities.executor import CapabilityExecutor
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import (
    CapabilityArtifact,
    CapabilityDescriptor,
    ExecutionResult,
    RiskLevel,
    RunStatus,
)


def _login_gated_artifact() -> CapabilityArtifact:
    return CapabilityArtifact.model_validate(
        {
            "id": "login-gated-lookup",
            "version": 1,
            "name": "Login-gated lookup",
            "description": "Look up a member's balance behind a login",
            "lifecycle": "approved",
            "application": {
                "vendor": "Interface Demo",
                "product": "Legacy Member Servicing",
                "base_url": "http://127.0.0.1:8001/secure",
            },
            "inputs": [
                {"name": "memberId", "type": "string", "description": "Member id", "required": True},
                {"name": "username", "type": "string", "description": "Login username", "required": True},
                {
                    "name": "password",
                    "type": "string",
                    "description": "Login password",
                    "required": True,
                    "sensitive": True,
                },
            ],
            "outputs": [{"name": "savingsBalance", "type": "number", "description": "Savings balance"}],
            "steps": [],
            "success": {"kind": "url"},
            "discovered_by": "mock:v1",
        }
    )


def _resolution_for(artifact: CapabilityArtifact) -> CapabilityResolution:
    descriptor = CapabilityDescriptor(
        id=artifact.qualified_id,
        name=artifact.name,
        description=artifact.description,
        source="computer_use",
        input_schema={},
        output_schema={},
        risk=RiskLevel.READ_ONLY,
        trust="approved",
        reliability=1.0,
        tags=[],
    )
    candidate = CapabilityCandidate(
        descriptor=descriptor,
        semantic_score=1.0,
        input_compatible=True,
        output_compatible=True,
        trust_ok=True,
        policy_ok=True,
        tenant_ok=True,
        reliability=1.0,
        final_score=1.0,
    )
    return CapabilityResolution(
        step_id="step-1",
        resolution_type=ResolutionType.COMPUTER_USE_CAPABILITY,
        selected=candidate,
        reason="test fixture",
    )


class _FakeReplayEngine:
    def __init__(self) -> None:
        self.received_inputs: dict | None = None

    async def execute(self, artifact, inputs) -> ExecutionResult:
        self.received_inputs = inputs
        now = datetime.now(UTC)
        return ExecutionResult(
            run_id="fake-run",
            status=RunStatus.SUCCESS,
            capability_id=artifact.qualified_id,
            outputs={"savingsBalance": 1220.0},
            started_at=now,
            completed_at=now,
        )


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    store = ArtifactStore(tmp_path / "artifacts")
    store.save(_login_gated_artifact())
    return store


async def test_missing_credentials_fails_cleanly_with_admin_facing_message(artifact_store: ArtifactStore):
    executor = CapabilityExecutor(artifact_store, lambda: _FakeReplayEngine(), tenant_credential_store=None)
    resolution = _resolution_for(_login_gated_artifact())

    result = await executor.execute(resolution, {"memberId": "10002"}, client_id="demo-client")

    assert result.status == RunStatus.FAILURE
    assert result.error.code == "CREDENTIALS_REQUIRED"
    assert "credentials" in result.error.message.lower()
    assert "/v1/capabilities/{id}/credentials" in result.error.message


async def test_stored_credentials_are_auto_injected_at_execution_time(artifact_store: ArtifactStore, tmp_path: Path):
    credential_store = JSONTenantCredentialStore(tmp_path / "tenant_credentials")
    credential_store.save(
        TenantCredential(
            capability_id="login-gated-lookup.v1",
            client_id="demo-client",
            username="demo",
            password="letmein-2024",
        )
    )
    replay_engine = _FakeReplayEngine()
    executor = CapabilityExecutor(artifact_store, lambda: replay_engine, tenant_credential_store=credential_store)
    resolution = _resolution_for(_login_gated_artifact())

    result = await executor.execute(resolution, {"memberId": "10002"}, client_id="demo-client")

    assert result.status == RunStatus.SUCCESS
    assert replay_engine.received_inputs["username"] == "demo"
    assert replay_engine.received_inputs["password"] == "letmein-2024"


async def test_credentials_are_scoped_per_client(artifact_store: ArtifactStore, tmp_path: Path):
    """Credentials stored for one client must never leak into another client's execution --
    that's the entire point of keying the store by (capability_id, client_id)."""
    credential_store = JSONTenantCredentialStore(tmp_path / "tenant_credentials")
    credential_store.save(
        TenantCredential(
            capability_id="login-gated-lookup.v1",
            client_id="client-a",
            username="a-user",
            password="a-pass",
        )
    )
    executor = CapabilityExecutor(artifact_store, lambda: _FakeReplayEngine(), tenant_credential_store=credential_store)
    resolution = _resolution_for(_login_gated_artifact())

    result = await executor.execute(resolution, {"memberId": "10002"}, client_id="client-b")

    assert result.status == RunStatus.FAILURE
    assert result.error.code == "CREDENTIALS_REQUIRED"


async def test_no_login_capability_never_consults_credential_store(tmp_path: Path):
    """A capability that doesn't declare username/password inputs must execute without ever
    touching the credential store, client_id or not."""
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = CapabilityArtifact.model_validate(
        {
            "id": "open-lookup",
            "version": 1,
            "name": "Open lookup",
            "description": "No login required",
            "lifecycle": "approved",
            "application": {
                "vendor": "Interface Demo",
                "product": "Legacy Member Servicing",
                "base_url": "http://127.0.0.1:8001",
            },
            "inputs": [{"name": "memberId", "type": "string", "description": "Member id", "required": True}],
            "outputs": [{"name": "savingsBalance", "type": "number", "description": "Savings balance"}],
            "steps": [],
            "success": {"kind": "url"},
            "discovered_by": "mock:v1",
        }
    )
    store.save(artifact)
    executor = CapabilityExecutor(store, lambda: _FakeReplayEngine(), tenant_credential_store=None)
    resolution = _resolution_for(artifact)

    result = await executor.execute(resolution, {"memberId": "10002"}, client_id=None)

    assert result.status == RunStatus.SUCCESS
