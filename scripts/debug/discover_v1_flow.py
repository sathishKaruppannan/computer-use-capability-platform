"""Debug harness for the authenticated /v1 discover flow: capability resolver (cross-client
reuse check) -> Claude discovery fallback -> draft artifact -> admin approval -> execute ->
reuse on a second call for the same (service_type, system_identifier) pair.

Runs the real FastAPI app in-process via TestClient, against settings pointed at a throwaway
temp directory -- it never touches the real artifacts/, data/credentials/, or evidence/ under
the repo root, so it's safe to re-run.

Good breakpoints to set before running this under the debugger:
  - v1_routes.discover_v1                                    (the resolver entry point itself)
  - capabilities.store.ArtifactStore.find_approved_by_service_and_system  (the reuse check)
  - agent.discovery.ClaudeDiscoveryAgent.discover              (Claude discovery, only on a miss)
  - agent.discovery.ClaudeDiscoveryAgent._decide                (each observe-decide-act step)
  - v1_routes.execute_v1                                       (service_type re-check + replay)

Requires:
  - `make demo` running on port 8001 -- step 1 below drives a real browser against it.
  - ANTHROPIC_API_KEY set (.env or environment) -- step 1 makes a genuine, billed Claude call.
    This script does not mock discovery; that's the point of debugging the real flow.

Usage: run this file directly (F5 on the "Debug: v1 discover flow" launch config), or
`uv run python scripts/debug/discover_v1_flow.py`.
"""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from capability_platform.access.credentials import JSONCredentialStore, hash_password
from capability_platform.access.models import ClientCredential
from capability_platform.api import app as app_module
from capability_platform.models import ServiceType
from capability_platform.settings import settings

CLIENT_ID = "demo-client"
CLIENT_PASSWORD = "secret123"
SERVICE_TYPE = "member_savings_balance_lookup"
SYSTEM_IDENTIFIER = "legacy-member-servicing-demo"


def _configure_isolated_settings(root: Path) -> None:
    settings.artifact_dir = root / "artifacts"
    settings.credential_dir = root / "credentials"
    settings.tracking_dir = root / "tracking"
    settings.system_registry_path = root / "system_registry.json"
    settings.system_registry_path.parent.mkdir(parents=True, exist_ok=True)
    settings.system_registry_path.write_text(
        json.dumps(
            {
                "systems": [
                    {
                        "systemIdentifier": SYSTEM_IDENTIFIER,
                        "baseUrl": "http://127.0.0.1:8001",
                        "vendor": "Interface Demo",
                        "product": "Legacy Member Servicing",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    password_hash, password_salt = hash_password(CLIENT_PASSWORD)
    JSONCredentialStore(settings.credential_dir).save(
        ClientCredential(
            client_id=CLIENT_ID,
            password_hash=password_hash,
            password_salt=password_salt,
            authorized_service_types=[ServiceType(SERVICE_TYPE)],
            is_admin=True,
        )
    )


def _print(label: str, response) -> None:
    print(f"\n--- {label} ---")
    print(response.status_code, json.dumps(response.json(), indent=2))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _configure_isolated_settings(Path(tmp))
        client = TestClient(app_module.app)
        auth = (CLIENT_ID, CLIENT_PASSWORD)

        discover_request = {
            "service_type": SERVICE_TYPE,
            "system_identifier": SYSTEM_IDENTIFIER,
            "client_inquiry_id": "debug-req-001",
            "goal": "Find member 10001 and return savings balance",
        }

        first = client.post("/v1/discover", json=discover_request, auth=auth)
        _print("1) POST /v1/discover -- no approved match yet, so this runs Claude discovery", first)
        assert first.json()["reused_existing_capability"] is False
        capability_id = first.json()["capability_id"]

        approve = client.post(f"/v1/capabilities/{capability_id}/approve", auth=auth)
        _print(f"2) POST /v1/capabilities/{capability_id}/approve (admin-only)", approve)

        execute = client.post(
            f"/v1/capabilities/{capability_id}/execute",
            json={"client_inquiry_id": "debug-req-002", "inputs": {"memberId": "10002"}},
            auth=auth,
        )
        _print("3) POST .../execute -- deterministic replay, no LLM in this path", execute)

        second = client.post(
            "/v1/discover",
            json={**discover_request, "client_inquiry_id": "debug-req-003"},
            auth=auth,
        )
        _print(
            "4) POST /v1/discover again, same (service_type, system_identifier) -- "
            "reused_existing_capability should now be true, no Claude call",
            second,
        )
        assert second.json()["reused_existing_capability"] is True
        assert second.json()["capability_id"] == capability_id


if __name__ == "__main__":
    main()
