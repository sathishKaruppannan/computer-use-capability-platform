"""Unit coverage of the authenticated /v1 REST surface (T: production auth/authorization/
tracking/reuse layer). No live browser or Claude call needed — the reuse-path test proves that
by making discovery_agent() raise if it's ever called."""

import json

from fastapi.testclient import TestClient

from capability_platform.access.credentials import JSONCredentialStore, hash_password
from capability_platform.access.models import ClientCredential, InquiryRecord
from capability_platform.access.tracking import JSONInquiryTracker
from capability_platform.api import app as app_module
from capability_platform.api import v1_routes as v1_routes_module
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import (
    ApplicationBinding,
    CapabilityArtifact,
    Checkpoint,
    Locator,
    OutputSpec,
    ParameterSpec,
    ServiceType,
    Target,
)
from capability_platform.settings import settings as global_settings


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
