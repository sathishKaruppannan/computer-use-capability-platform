"""Real end-to-end coverage of the REST execute path against the live demo app.

test_capability_gating.py already proves the lifecycle gate (403 on a draft capability) using a
zero-step artifact — it never actually drives a browser. This proves POST
/capabilities/{id}/execute performs a genuine deterministic replay through FastAPI's own ASGI
app, the same call path a production caller/agent would use, and gets the identical
ExecutionResult shape back as CLI/MCP for both the success and business-outcome cases."""

import pytest
from fastapi.testclient import TestClient

from capability_platform.api import app as app_module


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.mark.e2e
def test_execute_success_via_rest(client):
    response = client.post(
        "/capabilities/lookup-member-savings-balance.v1/execute",
        json={"inputs": {"memberId": "10002"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["outputs"]["savingsBalance"] == 1220.0
    assert body["error"] is None


@pytest.mark.e2e
def test_execute_business_outcome_via_rest(client):
    response = client.post(
        "/capabilities/lookup-member-savings-balance.v1/execute",
        json={"inputs": {"memberId": "99999"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "business_outcome"
    assert body["business_code"] == "MEMBER_NOT_FOUND"
    assert body["error"] is None


@pytest.mark.e2e
def test_execute_unknown_capability_returns_404(client):
    response = client.post("/capabilities/does-not-exist.v1/execute", json={"inputs": {}})
    assert response.status_code == 404


@pytest.mark.e2e
def test_list_capabilities_via_rest_includes_the_approved_artifact(client):
    response = client.get("/capabilities")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()}
    assert "lookup-member-savings-balance.v1" in ids
