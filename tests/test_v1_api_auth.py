"""Unit coverage of the authenticated /v1 REST surface (T: production auth/authorization/
tracking/reuse layer). No live browser or Claude call needed — the reuse-path test proves that
by making discovery_agent() raise if it's ever called."""

import json

from fastapi.testclient import TestClient

from capability_platform.access.credentials import JSONCredentialStore, hash_password
from capability_platform.access.models import ClientCredential, InquiryRecord
from capability_platform.access.tenant_credentials import JSONTenantCredentialStore
from capability_platform.access.tracking import JSONInquiryTracker
from capability_platform.agent.models import (
    CapabilityCandidate,
    CapabilityResolution,
    ResolutionType,
)
from capability_platform.api import app as app_module
from capability_platform.api import v1_routes as v1_routes_module
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import (
    ApplicationBinding,
    CapabilityArtifact,
    CapabilityDescriptor,
    Checkpoint,
    Locator,
    OutputSpec,
    ParameterSpec,
    RiskLevel,
    ServiceType,
    Target,
)
from capability_platform.settings import settings as global_settings


def _computer_use_resolution(descriptor_id: str, step_id: str = "step-1") -> CapabilityResolution:
    descriptor = CapabilityDescriptor(
        id=descriptor_id,
        name="Semantic candidate",
        description="test",
        source="computer_use",
        input_schema={},
        output_schema={},
        risk=RiskLevel.READ_ONLY,
        trust="approved",
    )
    candidate = CapabilityCandidate(
        descriptor=descriptor,
        semantic_score=0.9,
        input_compatible=True,
        output_compatible=True,
        trust_ok=True,
        policy_ok=True,
        tenant_ok=True,
        reliability=1.0,
        final_score=0.9,
    )
    return CapabilityResolution(
        step_id=step_id, resolution_type=ResolutionType.COMPUTER_USE_CAPABILITY, selected=candidate, reason="matched"
    )


def _artifact(id_: str, lifecycle: str, service_type=None, system_identifier=None) -> CapabilityArtifact:
    return CapabilityArtifact(
        id=id_,
        name="Test capability",
        description="test",
        lifecycle=lifecycle,
        application=ApplicationBinding(vendor="x", product="y", base_url="http://127.0.0.1:8001"),
        inputs=[ParameterSpec(name="memberId", type="string", description="x")],
        outputs=[OutputSpec(name="out", type="string", description="x")],
        steps=[],
        success=Checkpoint(
            kind="visible",
            target=Target(primary=Locator(strategy="text", value="x"), rationale="x"),
        ),
        discovered_by="test",
        service_type=service_type,
        system_identifier=system_identifier,
    )


def _register_client(client_id, password, service_types, is_admin=False):
    password_hash, password_salt = hash_password(password)
    JSONCredentialStore(global_settings.credential_dir).save(
        ClientCredential(
            client_id=client_id,
            password_hash=password_hash,
            password_salt=password_salt,
            authorized_service_types=service_types,
            is_admin=is_admin,
        )
    )


def _write_system_registry(system_identifier="legacy-member-servicing-demo", base_url="http://127.0.0.1:8001"):
    global_settings.system_registry_path.write_text(
        json.dumps(
            {
                "systems": [
                    {
                        "systemIdentifier": system_identifier,
                        "baseUrl": base_url,
                        "vendor": "Interface Demo",
                        "product": "Legacy Member Servicing",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _configure(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "artifact_dir", tmp_path / "artifacts")
    monkeypatch.setattr(global_settings, "credential_dir", tmp_path / "credentials")
    monkeypatch.setattr(global_settings, "tracking_dir", tmp_path / "tracking")
    monkeypatch.setattr(global_settings, "system_registry_path", tmp_path / "system_registry.json")
    # Defense in depth: a real (unmocked) discovery/intent-analysis call reaching this point would
    # otherwise write real evidence into the actual evidence/ directory even though every other
    # piece of state is isolated to tmp_path -- found the hard way when _find_semantic_reuse's
    # agent_orchestrator() call did exactly that before the mocks below existed.
    monkeypatch.setattr(global_settings, "evidence_dir", tmp_path / "evidence")
    monkeypatch.setattr(global_settings, "tenant_credential_dir", tmp_path / "tenant_credentials")


def _no_semantic_match(monkeypatch):
    """discover_v1 now tries a semantic-reuse check (agent_orchestrator().plan_only(...)) before
    falling through to discovery. Without this, any test reaching that branch would construct a
    REAL AnthropicProvider (this dev environment has a real ANTHROPIC_API_KEY configured) and
    make a live network call -- turning a fast, offline unit test into a slow, non-deterministic,
    networked one. Force it to report "no match" instantly, same as an absent/misconfigured
    provider would in CI."""

    class _NoSemanticMatchOrchestrator:
        async def plan_only(self, goal, context=None):
            raise RuntimeError("no semantic match in this test")

    monkeypatch.setattr(v1_routes_module, "agent_orchestrator", lambda: _NoSemanticMatchOrchestrator())


def test_discover_v1_requires_authentication(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-001",
            "goal": "irrelevant",
        },
    )
    assert response.status_code == 401


def test_discover_v1_rejects_goal_over_length_limit(monkeypatch, tmp_path):
    """Rejected by Pydantic (DiscoverV1Request.goal's max_length) before authentication or
    discovery are ever reached -- no risk of a real LLM call."""
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-toolong",
            "goal": "x" * (global_settings.max_goal_length + 1),
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 422


def test_discover_v1_rejects_bad_password(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-001",
            "goal": "irrelevant",
        },
        auth=("demo-client", "wrong-pw"),
    )
    assert response.status_code == 401


def test_discover_v1_rejects_service_type_not_authorized(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [])  # authorized for nothing
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-001",
            "goal": "irrelevant",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 403


def test_discover_v1_reuses_existing_approved_capability_without_calling_discovery(
    monkeypatch, tmp_path
):
    """The zero-LLM reuse proof: discovery_agent() is monkeypatched to raise if called at all."""
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    ArtifactStore(global_settings.artifact_dir).save(
        _artifact(
            "balance-cap",
            "approved",
            service_type=ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP,
            system_identifier="legacy-member-servicing-demo",
        )
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("discovery_agent() must not be called on the reuse path")

    monkeypatch.setattr(v1_routes_module, "discovery_agent", _fail_if_called)

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-002",
            "goal": "Find member 10002 and return savings balance",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reused_existing_capability"] is True
    assert body["capability_id"] == "balance-cap.v1"
    assert body["lifecycle"] == "approved"
    assert body["approval_required"] is False  # already approved, nothing left to do

    tracked = JSONInquiryTracker(global_settings.tracking_dir).get(body["inquiry_id"])
    assert tracked is not None
    assert tracked.client_inquiry_id == "client-req-002"
    assert tracked.client_id == "demo-client"
    assert tracked.reused_existing_capability is True


def test_discover_v1_unknown_system_identifier_returns_400(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    # No matching approved capability and an empty system registry -> discovery would be
    # attempted, but system_identifier resolution fails first.
    global_settings.system_registry_path.write_text(json.dumps({"systems": []}), encoding="utf-8")
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "never-registered-system",
            "client_inquiry_id": "client-req-003",
            "goal": "irrelevant",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 400


def test_discover_v1_runs_discovery_and_saves_new_capability_when_no_reuse_match(
    monkeypatch, tmp_path
):
    """The other half of the discover branch: no existing approved match, so discovery runs —
    with a fake discovery_agent (no real Claude call) returning a canned draft artifact, whose
    service_type/system_identifier the route must stamp on before saving."""
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()

    fake_artifact = _artifact("fresh-cap", "draft")

    class _FakeAgent:
        async def discover(
            self, goal, target_url, member_id,
            extra_known_values=None, system_identifier=None, run_id=None,
        ):
            assert target_url == "http://127.0.0.1:8001"
            return fake_artifact

    calls: list[str] = []

    def _fake_discovery_agent(environment="production"):
        calls.append(environment)
        return _FakeAgent()

    monkeypatch.setattr(v1_routes_module, "discovery_agent", _fake_discovery_agent)
    _no_semantic_match(monkeypatch)

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-006",
            "goal": "Find member 10001 and return savings balance",
            "environment": "demo",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reused_existing_capability"] is False
    assert body["lifecycle"] == "draft"
    assert body["approval_required"] is True  # fresh draft, an admin still has to approve it
    assert calls == ["demo"]

    saved = ArtifactStore(global_settings.artifact_dir).load(body["capability_id"])
    assert saved.service_type == ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP
    assert saved.system_identifier == "legacy-member-servicing-demo"

    tracked = JSONInquiryTracker(global_settings.tracking_dir).get(body["inquiry_id"])
    assert tracked is not None
    assert tracked.reused_existing_capability is False
    assert tracked.environment == "demo"


def test_discover_v1_is_auth_required_without_credentials_returns_400(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    _no_semantic_match(monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-auth-1",
            "goal": "Log in and return savings balance",
            "is_auth_required": True,
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 400
    assert "example_username" in response.json()["detail"]


def test_discover_v1_passes_extra_known_values_when_auth_required(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    fake_artifact = _artifact("auth-cap", "draft")
    received: dict = {}

    class _FakeAgent:
        async def discover(
            self, goal, target_url, member_id,
            extra_known_values=None, system_identifier=None, run_id=None,
        ):
            received["extra_known_values"] = extra_known_values
            return fake_artifact

    monkeypatch.setattr(v1_routes_module, "discovery_agent", lambda environment="production": _FakeAgent())
    _no_semantic_match(monkeypatch)

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-auth-2",
            "goal": "Log in and return savings balance",
            "is_auth_required": True,
            "example_username": "demo",
            "example_password": "letmein-2024",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    assert received["extra_known_values"] == {"username": "demo", "password": "letmein-2024"}


def test_discover_v1_api_key_auth_without_key_returns_400(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    _no_semantic_match(monkeypatch)
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-apikey-1",
            "goal": "Authenticate with an API key and return savings balance",
            "is_auth_required": True,
            "auth_type": "api_key",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 400
    assert "example_api_key" in response.json()["detail"]


def test_discover_v1_passes_api_key_as_extra_known_values(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    fake_artifact = _artifact("apikey-cap", "draft")
    received: dict = {}

    class _FakeAgent:
        async def discover(
            self, goal, target_url, member_id,
            extra_known_values=None, system_identifier=None, run_id=None,
        ):
            received["extra_known_values"] = extra_known_values
            return fake_artifact

    monkeypatch.setattr(v1_routes_module, "discovery_agent", lambda environment="production": _FakeAgent())
    _no_semantic_match(monkeypatch)

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-apikey-2",
            "goal": "Authenticate with an API key and return savings balance",
            "is_auth_required": True,
            "auth_type": "api_key",
            "example_api_key": "sk-demo-abc123",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    assert received["extra_known_values"] == {"apiKey": "sk-demo-abc123"}


def test_discover_v1_force_rediscover_skips_reuse_and_calls_discovery(monkeypatch, tmp_path):
    """Inverse of the reuse test above: force_rediscover=True must run discovery even though an
    approved match exists."""
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    ArtifactStore(global_settings.artifact_dir).save(
        _artifact(
            "balance-cap",
            "approved",
            service_type=ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP,
            system_identifier="legacy-member-servicing-demo",
        )
    )
    fresh_artifact = _artifact("balance-cap", "draft")
    called = {"count": 0}

    class _FakeAgent:
        async def discover(
            self, goal, target_url, member_id,
            extra_known_values=None, system_identifier=None, run_id=None,
        ):
            called["count"] += 1
            return fresh_artifact

    monkeypatch.setattr(v1_routes_module, "discovery_agent", lambda environment="production": _FakeAgent())

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-force-1",
            "goal": "Find member 10001 and return savings balance",
            "force_rediscover": True,
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    assert called["count"] == 1
    assert response.json()["reused_existing_capability"] is False


def test_discover_v1_target_url_bypasses_registry(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    # Deliberately empty registry -- system_identifier below is never registered.
    global_settings.system_registry_path.write_text(json.dumps({"systems": []}), encoding="utf-8")
    fake_artifact = _artifact("bypass-cap", "draft")
    received: dict = {}

    class _FakeAgent:
        async def discover(
            self, goal, target_url, member_id,
            extra_known_values=None, system_identifier=None, run_id=None,
        ):
            received["target_url"] = target_url
            return fake_artifact

    monkeypatch.setattr(v1_routes_module, "discovery_agent", lambda environment="production": _FakeAgent())
    _no_semantic_match(monkeypatch)

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "not-in-any-registry",
            "client_inquiry_id": "client-req-bypass-1",
            "goal": "Find member 10001 and return savings balance",
            "target_url": "http://127.0.0.1:8001/secure",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    assert received["target_url"] == "http://127.0.0.1:8001/secure"


def test_discover_v1_passes_discovery_run_id_through(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    fake_artifact = _artifact("run-id-cap", "draft")
    received: dict = {}

    class _FakeAgent:
        async def discover(
            self, goal, target_url, member_id,
            extra_known_values=None, system_identifier=None, run_id=None,
        ):
            received["run_id"] = run_id
            return fake_artifact

    monkeypatch.setattr(v1_routes_module, "discovery_agent", lambda environment="production": _FakeAgent())
    _no_semantic_match(monkeypatch)

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-runid-1",
            "goal": "Find member 10001 and return savings balance",
            "discovery_run_id": "client-generated-run-id-123",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    assert received["run_id"] == "client-generated-run-id-123"


def test_list_systems_v1_returns_registered_systems(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _write_system_registry()
    client = TestClient(app_module.app)

    response = client.get("/v1/systems")  # no auth= kwarg -- proves it's unauthenticated
    assert response.status_code == 200
    systems = response.json()["systems"]
    assert any(s["system_identifier"] == "legacy-member-servicing-demo" for s in systems)
    assert systems[0]["base_url"] == "http://127.0.0.1:8001"


def test_execute_v1_requires_service_type_authorization(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [])  # not authorized for the capability's type
    ArtifactStore(global_settings.artifact_dir).save(
        _artifact(
            "balance-cap",
            "approved",
            service_type=ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP,
            system_identifier="legacy-member-servicing-demo",
        )
    )
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/balance-cap.v1/execute",
        json={"client_inquiry_id": "client-req-004", "inputs": {"memberId": "10002"}},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 403


def test_execute_v1_unknown_capability_returns_404(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/does-not-exist.v1/execute",
        json={"client_inquiry_id": "client-req-005", "inputs": {}},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 404


def test_approve_v1_requires_admin(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=False)
    ArtifactStore(global_settings.artifact_dir).save(_artifact("draft-cap", "draft"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/draft-cap.v1/approve", auth=("demo-client", "correct-pw")
    )
    assert response.status_code == 403


def test_approve_v1_succeeds_for_admin(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    ArtifactStore(global_settings.artifact_dir).save(_artifact("draft-cap", "draft"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/draft-cap.v1/approve", auth=("admin-client", "correct-pw")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle"] == "approved"

    reloaded = ArtifactStore(global_settings.artifact_dir).load("draft-cap.v1")
    assert reloaded.lifecycle == "approved"


def _login_gated_artifact(id_: str, lifecycle: str) -> CapabilityArtifact:
    return CapabilityArtifact(
        id=id_,
        name="Login-gated capability",
        description="test",
        lifecycle=lifecycle,
        application=ApplicationBinding(vendor="x", product="y", base_url="http://127.0.0.1:8001/secure"),
        inputs=[
            ParameterSpec(name="memberId", type="string", description="x"),
            ParameterSpec(name="username", type="string", description="login username"),
            ParameterSpec(name="password", type="string", description="login password", sensitive=True),
        ],
        outputs=[OutputSpec(name="out", type="string", description="x")],
        steps=[],
        success=Checkpoint(
            kind="visible",
            target=Target(primary=Locator(strategy="text", value="x"), rationale="x"),
        ),
        discovered_by="test",
    )


def test_approve_v1_with_credentials_saves_them_for_that_client(monkeypatch, tmp_path):
    """The combined approve+save-credentials convenience: an admin can approve a login-gated
    draft and immediately hand it credentials for one client in a single call."""
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    ArtifactStore(global_settings.artifact_dir).save(_login_gated_artifact("secure-cap", "draft"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/secure-cap.v1/approve",
        json={"client_id": "demo-client", "username": "demo", "password": "letmein-2024"},
        auth=("admin-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle"] == "approved"
    assert body["credentials_saved_for_client"] == "demo-client"

    stored = JSONTenantCredentialStore(global_settings.tenant_credential_dir).get("secure-cap.v1", "demo-client")
    assert stored is not None
    assert stored.username == "demo"
    assert stored.password == "letmein-2024"


def test_approve_v1_without_credentials_leaves_credentials_saved_for_client_none(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    ArtifactStore(global_settings.artifact_dir).save(_artifact("draft-cap", "draft"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/draft-cap.v1/approve", auth=("admin-client", "correct-pw")
    )
    assert response.status_code == 200
    assert response.json()["credentials_saved_for_client"] is None


def test_save_credentials_v1_requires_admin(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=False)
    ArtifactStore(global_settings.artifact_dir).save(_login_gated_artifact("secure-cap", "approved"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/secure-cap.v1/credentials",
        json={"client_id": "demo-client", "username": "demo", "password": "letmein-2024"},
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 403


def test_save_credentials_v1_allows_a_still_draft_capability(monkeypatch, tmp_path):
    """Storing credentials never grants execution access on its own -- only an approved/active
    capability can actually be invoked, checked separately at every execute path -- so an admin
    can set up a login-gated capability in either order: approve then add credentials, or add
    credentials then approve. Draft-state credentials just sit ready for when it's approved."""
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    ArtifactStore(global_settings.artifact_dir).save(_login_gated_artifact("secure-cap", "draft"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/secure-cap.v1/credentials",
        json={"client_id": "demo-client", "username": "demo", "password": "letmein-2024"},
        auth=("admin-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"capability_id": "secure-cap.v1", "client_id": "demo-client", "saved": True}

    stored = JSONTenantCredentialStore(global_settings.tenant_credential_dir).get("secure-cap.v1", "demo-client")
    assert stored is not None
    assert stored.username == "demo"


def test_save_credentials_v1_rejects_capability_without_credential_inputs(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    ArtifactStore(global_settings.artifact_dir).save(_artifact("open-cap", "approved"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/open-cap.v1/credentials",
        json={"client_id": "demo-client", "username": "demo", "password": "letmein-2024"},
        auth=("admin-client", "correct-pw"),
    )
    assert response.status_code == 400


def test_save_credentials_v1_succeeds_for_a_second_client_on_an_already_approved_capability(
    monkeypatch, tmp_path
):
    """The multi-tenant reuse point: a second client gets its own stored credentials for the
    same already-approved capability, without re-approving it."""
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    ArtifactStore(global_settings.artifact_dir).save(_login_gated_artifact("secure-cap", "approved"))
    client = TestClient(app_module.app)

    response = client.post(
        "/v1/capabilities/secure-cap.v1/credentials",
        json={"client_id": "second-client", "username": "second", "password": "second-pw"},
        auth=("admin-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"capability_id": "secure-cap.v1", "client_id": "second-client", "saved": True}

    stored = JSONTenantCredentialStore(global_settings.tenant_credential_dir).get("secure-cap.v1", "second-client")
    assert stored is not None
    assert stored.username == "second"


def test_list_pending_v1_requires_admin(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=False)
    client = TestClient(app_module.app)

    response = client.get("/v1/capabilities/pending", auth=("demo-client", "correct-pw"))
    assert response.status_code == 403


def test_list_pending_v1_returns_only_drafts(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    artifact_store = ArtifactStore(global_settings.artifact_dir)
    artifact_store.save(_artifact("draft-cap", "draft"))
    artifact_store.save(_artifact("approved-cap", "approved"))
    artifact_store.save(_artifact("active-cap", "active"))
    client = TestClient(app_module.app)

    response = client.get("/v1/capabilities/pending", auth=("admin-client", "correct-pw"))
    assert response.status_code == 200
    ids = {c["capability_id"] for c in response.json()["capabilities"]}
    assert ids == {"draft-cap.v1"}


def test_review_v1_requires_admin(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=False)
    ArtifactStore(global_settings.artifact_dir).save(_artifact("draft-cap", "draft"))
    client = TestClient(app_module.app)

    response = client.get("/v1/capabilities/draft-cap.v1/review", auth=("demo-client", "correct-pw"))
    assert response.status_code == 403


def test_review_v1_unknown_capability_returns_404(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    client = TestClient(app_module.app)

    response = client.get(
        "/v1/capabilities/does-not-exist.v1/review", auth=("admin-client", "correct-pw")
    )
    assert response.status_code == 404


def test_review_v1_includes_goal_and_requester(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("admin-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP], is_admin=True)
    ArtifactStore(global_settings.artifact_dir).save(_artifact("draft-cap", "draft"))
    JSONInquiryTracker(global_settings.tracking_dir).record(
        InquiryRecord(
            inquiry_id="inq-1",
            client_inquiry_id="client-req-001",
            client_id="requesting-client",
            goal="Look up a member's savings balance",
            capability_id="draft-cap.v1",
        )
    )
    client = TestClient(app_module.app)

    response = client.get("/v1/capabilities/draft-cap.v1/review", auth=("admin-client", "correct-pw"))
    assert response.status_code == 200
    body = response.json()
    assert body["lifecycle"] == "draft"
    assert len(body["requested_by"]) == 1
    assert body["requested_by"][0]["client_id"] == "requesting-client"
    assert body["requested_by"][0]["goal"] == "Look up a member's savings balance"


async def test_find_semantic_reuse_returns_artifact_when_base_url_matches(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    ArtifactStore(global_settings.artifact_dir).save(_artifact("semantic-cap", "approved"))
    resolution = _computer_use_resolution("semantic-cap.v1")

    class _FakeOrchestrator:
        async def plan_only(self, goal, context=None):
            return None, None, [resolution]

    monkeypatch.setattr(v1_routes_module, "agent_orchestrator", lambda: _FakeOrchestrator())

    found = await v1_routes_module._find_semantic_reuse(
        "Get the savings balance for member 10002", "http://127.0.0.1:8001"
    )
    assert found is not None
    assert found.qualified_id == "semantic-cap.v1"


async def test_find_semantic_reuse_filters_out_a_different_target_application(monkeypatch, tmp_path):
    """Tenant/target-isolation safety: a semantic match on goal text alone is not enough --
    the matched capability's own base_url must equal the resolved target for THIS request."""
    _configure(monkeypatch, tmp_path)
    other_app = _artifact("other-app-cap", "approved")
    other_app.application.base_url = "http://127.0.0.1:9999"
    ArtifactStore(global_settings.artifact_dir).save(other_app)
    resolution = _computer_use_resolution("other-app-cap.v1")

    class _FakeOrchestrator:
        async def plan_only(self, goal, context=None):
            return None, None, [resolution]

    monkeypatch.setattr(v1_routes_module, "agent_orchestrator", lambda: _FakeOrchestrator())

    found = await v1_routes_module._find_semantic_reuse("goal", "http://127.0.0.1:8001")
    assert found is None


async def test_find_semantic_reuse_returns_none_on_any_resolver_error(monkeypatch, tmp_path):
    """Never lets a failure here (missing credentials, a transient provider error, anything)
    block the existing, proven discovery fallback."""
    _configure(monkeypatch, tmp_path)

    class _RaisingOrchestrator:
        async def plan_only(self, goal, context=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(v1_routes_module, "agent_orchestrator", lambda: _RaisingOrchestrator())

    found = await v1_routes_module._find_semantic_reuse("goal", "http://127.0.0.1:8001")
    assert found is None


def test_discover_v1_reuses_capability_via_semantic_match_when_exact_key_misses(monkeypatch, tmp_path):
    """The actual point of unifying the two resolution paths: a capability discovered OUTSIDE
    /v1/discover's own flow (e.g. via the plain `discover` CLI command, or via /agent/execute's
    own discovery fallback -- neither of which stamps service_type/system_identifier) can now be
    reused here too, via base_url + semantic goal match, instead of triggering redundant fresh
    discovery just because the exact-key pair was never registered."""
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    # service_type/system_identifier=None -- exactly what a capability discovered outside
    # /v1/discover's own flow looks like.
    ArtifactStore(global_settings.artifact_dir).save(_artifact("outside-cap", "approved"))
    resolution = _computer_use_resolution("outside-cap.v1")

    class _FakeOrchestrator:
        async def plan_only(self, goal, context=None):
            return None, None, [resolution]

    monkeypatch.setattr(v1_routes_module, "agent_orchestrator", lambda: _FakeOrchestrator())

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("discovery_agent() must not be called when a semantic match is found")

    monkeypatch.setattr(v1_routes_module, "discovery_agent", _fail_if_called)

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-semantic-1",
            "goal": "Find member 10002 and return savings balance",
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reused_existing_capability"] is True
    assert body["capability_id"] == "outside-cap.v1"

    tracked = JSONInquiryTracker(global_settings.tracking_dir).get(body["inquiry_id"])
    assert tracked is not None
    assert tracked.reused_existing_capability is True


def test_discover_v1_force_rediscover_also_skips_semantic_match(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    _register_client("demo-client", "correct-pw", [ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP])
    _write_system_registry()
    ArtifactStore(global_settings.artifact_dir).save(_artifact("would-match-cap", "approved"))

    def _fail_if_called(goal, context=None):
        raise AssertionError("semantic match must not be attempted when force_rediscover=True")

    class _FailingOrchestrator:
        async def plan_only(self, goal, context=None):
            _fail_if_called(goal, context)

    monkeypatch.setattr(v1_routes_module, "agent_orchestrator", lambda: _FailingOrchestrator())

    fresh_artifact = _artifact("would-match-cap", "draft")

    class _FakeAgent:
        async def discover(
            self, goal, target_url, member_id, extra_known_values=None, system_identifier=None, run_id=None
        ):
            return fresh_artifact

    monkeypatch.setattr(v1_routes_module, "discovery_agent", lambda environment="production": _FakeAgent())

    client = TestClient(app_module.app)
    response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "client-req-force-2",
            "goal": "Find member 10001 and return savings balance",
            "force_rediscover": True,
        },
        auth=("demo-client", "correct-pw"),
    )
    assert response.status_code == 200
    assert response.json()["reused_existing_capability"] is False
