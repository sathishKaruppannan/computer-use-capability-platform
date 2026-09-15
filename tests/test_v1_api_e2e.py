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
                    }
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
