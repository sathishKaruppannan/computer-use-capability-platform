"""Real end-to-end coverage of the authenticated /v1 surface: a genuine Claude discovery run
against the live demo app, followed by admin approval and a real replay — the analogue of
test_rest_api_e2e.py for the new authenticated path. Isolated to tmp_path settings so it never
writes into the real artifacts/ or data/ directories and stays repeatable across runs."""

import json

import pytest
from fastapi.testclient import TestClient

from capability_platform.access.credentials import JSONCredentialStore, hash_password
from capability_platform.access.models import ClientCredential
from capability_platform.api import app as app_module
from capability_platform.models import ServiceType
from capability_platform.settings import settings as global_settings


def _configure(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "artifact_dir", tmp_path / "artifacts")
    monkeypatch.setattr(global_settings, "credential_dir", tmp_path / "credentials")
    monkeypatch.setattr(global_settings, "tracking_dir", tmp_path / "tracking")
    monkeypatch.setattr(global_settings, "system_registry_path", tmp_path / "system_registry.json")
    global_settings.system_registry_path.parent.mkdir(parents=True, exist_ok=True)
    global_settings.system_registry_path.write_text(
        json.dumps(
            {
                "systems": [
                    {
                        "systemIdentifier": "legacy-member-servicing-demo",
                        "baseUrl": "http://127.0.0.1:8001",
                        "vendor": "Interface Demo",
                        "product": "Legacy Member Servicing",
                    },
                    {
                        "systemIdentifier": "legacy-member-servicing-demo-secure",
                        "baseUrl": "http://127.0.0.1:8001/secure",
                        "vendor": "Interface Demo",
                        "product": "Legacy Member Servicing (Auth-Required)",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    password_hash, password_salt = hash_password("secret123")
    JSONCredentialStore(global_settings.credential_dir).save(
        ClientCredential(
            client_id="demo-client",
            password_hash=password_hash,
            password_salt=password_salt,
            authorized_service_types=[ServiceType.MEMBER_SAVINGS_BALANCE_LOOKUP],
            is_admin=True,
        )
    )


@pytest.mark.e2e
def test_authenticated_discover_approve_execute_round_trip(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app_module.app)
    auth = ("demo-client", "secret123")

    discover_response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "e2e-client-req-001",
            "goal": "Find member 10001 and return savings balance",
        },
        auth=auth,
    )
    assert discover_response.status_code == 200
    discovered = discover_response.json()
    assert discovered["reused_existing_capability"] is False
    assert discovered["lifecycle"] == "draft"
    capability_id = discovered["capability_id"]

    approve_response = client.post(f"/v1/capabilities/{capability_id}/approve", auth=auth)
    assert approve_response.status_code == 200
    assert approve_response.json()["lifecycle"] == "approved"

    execute_response = client.post(
        f"/v1/capabilities/{capability_id}/execute",
        json={"client_inquiry_id": "e2e-client-req-002", "inputs": {"memberId": "10002"}},
        auth=auth,
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    assert result["status"] == "success"
    assert result["outputs"]["savingsBalance"] == 1220.0
    assert result["error"] is None

    # Second discover call for the same (service_type, system_identifier) pair must now reuse
    # the just-approved capability instead of discovering again.
    reuse_response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "e2e-client-req-003",
            "goal": "Find member 10001 and return savings balance",
        },
        auth=auth,
    )
    assert reuse_response.status_code == 200
    assert reuse_response.json()["reused_existing_capability"] is True
    assert reuse_response.json()["capability_id"] == capability_id


@pytest.mark.e2e
def test_auth_required_discover_finds_login_form_and_completes_goal(monkeypatch, tmp_path):
    """The real thing this feature is about: Claude discovers the /secure login form itself
    (not a hardcoded login step), types the example credentials, and continues to the goal.
    Also proves the artifact never bakes in the literal credential and that a real caller can
    replay with credentials supplied independently at execute time."""
    _configure(monkeypatch, tmp_path)
    client = TestClient(app_module.app)
    auth = ("demo-client", "secret123")

    discover_response = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo-secure",
            "client_inquiry_id": "e2e-auth-req-001",
            "goal": "Log in, then find member 10001 and return savings balance",
            "is_auth_required": True,
            "example_username": "demo",
            "example_password": "letmein-2024",
        },
        auth=auth,
    )
    assert discover_response.status_code == 200
    discovered = discover_response.json()
    assert discovered["reused_existing_capability"] is False
    assert discovered["lifecycle"] == "draft"
    capability_id = discovered["capability_id"]
    # Distinct from the plain (non-auth) capability discovered above -- proves the two
    # system_identifiers coexist as independent capabilities.
    assert capability_id != "lookup-member-savings-balance.v1"

    artifact_response = client.get(f"/v1/capabilities/{capability_id}/review", auth=auth)
    assert artifact_response.status_code == 200
    artifact = artifact_response.json()
    input_names = {spec["name"] for spec in artifact["inputs"]}
    assert {"memberId", "username", "password"} <= input_names
    password_spec = next(s for s in artifact["inputs"] if s["name"] == "password")
    assert password_spec["sensitive"] is True
    # The literal example credential must never appear anywhere in the compiled artifact --
    # only the {{username}}/{{password}} placeholders, in step values AND step descriptions
    # (Claude's own reasoning text, which is a separate leak path from step.value).
    artifact_text = json.dumps(artifact)
    assert "letmein-2024" not in artifact_text
    assert any(step["value"] == "{{password}}" for step in artifact["steps"])

    approve_response = client.post(f"/v1/capabilities/{capability_id}/approve", auth=auth)
    assert approve_response.status_code == 200

    # Real caller supplies credentials independently at execute time -- same mechanism as
    # memberId, no relation to the discovery-time example values beyond happening to be the
    # only credential this demo app's /secure area actually accepts.
    execute_response = client.post(
        f"/v1/capabilities/{capability_id}/execute",
        json={
            "client_inquiry_id": "e2e-auth-req-002",
            "inputs": {"memberId": "10002", "username": "demo", "password": "letmein-2024"},
        },
        auth=auth,
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    assert result["status"] == "success"
    assert result["outputs"]["savingsBalance"] == 1220.0


@pytest.mark.e2e
def test_force_rediscover_runs_fresh_discovery_and_updates_same_capability(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app_module.app)
    auth = ("demo-client", "secret123")

    first = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "e2e-force-req-001",
            "goal": "Find member 10001 and return savings balance",
        },
        auth=auth,
    )
    assert first.status_code == 200
    capability_id = first.json()["capability_id"]
    client.post(f"/v1/capabilities/{capability_id}/approve", auth=auth)
    first_created_at = client.get(f"/v1/capabilities/{capability_id}/review", auth=auth).json()[
        "created_at"
    ]

    second = client.post(
        "/v1/discover",
        json={
            "service_type": "member_savings_balance_lookup",
            "system_identifier": "legacy-member-servicing-demo",
            "client_inquiry_id": "e2e-force-req-002",
            "goal": "Find member 10001 and return savings balance",
            "force_rediscover": True,
        },
        auth=auth,
    )
    assert second.status_code == 200
    # A genuine second discovery ran (not a reuse of the just-approved capability), and it
    # overwrote the same capability_id rather than creating a new one.
    assert second.json()["reused_existing_capability"] is False
    assert second.json()["capability_id"] == capability_id

    second_created_at = client.get(f"/v1/capabilities/{capability_id}/review", auth=auth).json()[
        "created_at"
    ]
    assert second_created_at != first_created_at
