"""Coverage for the demo-dashboard-only endpoints added to api/app.py: the shared demo-capability
builders (capabilities/demo_seed.py), POST /admin/seed-demo-capabilities, and
GET /runs/{run_id}/events. The dashboard's own HTML/JS (api/admin.py) has no automated test —
verified by hand in a browser, see docs/REST_API_TEST_SCENARIOS.md."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from capability_platform.api import app as app_module
from capability_platform.capabilities.demo_seed import (
    APPROVAL_DEMO_ID,
    PAUSE_DEMO_ID,
    build_approval_demo,
    build_pause_demo,
)
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import ErrorCategory, RiskLevel
from capability_platform.settings import settings as global_settings


def test_build_pause_demo_injects_pause_error_rule():
    store = ArtifactStore(Path("artifacts"))
    demo = build_pause_demo(store)
    assert demo.id == PAUSE_DEMO_ID
    assert demo.lifecycle == "approved"
    injected = demo.steps[1].errors[-1]
    assert injected.recovery == "pause"
    assert injected.category == ErrorCategory.RECOVERABLE
    assert injected.when.target.primary.value == "Session Notice"


def test_build_approval_demo_marks_step_risky():
    store = ArtifactStore(Path("artifacts"))
    demo = build_approval_demo(store)
    assert demo.id == APPROVAL_DEMO_ID
    assert demo.lifecycle == "approved"
    assert demo.steps[2].risk == RiskLevel.RISKY


def test_seed_demo_capabilities_creates_both(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "artifact_dir", tmp_path / "artifacts")
    ArtifactStore(tmp_path / "artifacts").save(
        ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    )
    client = TestClient(app_module.app)

    response = client.post("/admin/seed-demo-capabilities")
    assert response.status_code == 200
    seeded = response.json()["seeded"]
    assert seeded == [f"{PAUSE_DEMO_ID}.v1", f"{APPROVAL_DEMO_ID}.v1"]

    store = ArtifactStore(tmp_path / "artifacts")
    assert store.load(seeded[0]).lifecycle == "approved"
    assert store.load(seeded[1]).lifecycle == "approved"


def test_seed_demo_capabilities_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "artifact_dir", tmp_path / "artifacts")
    ArtifactStore(tmp_path / "artifacts").save(
        ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    )
    client = TestClient(app_module.app)

    first = client.post("/admin/seed-demo-capabilities").json()
    second = client.post("/admin/seed-demo-capabilities").json()
    assert first == second


def test_seed_demo_capabilities_404_without_base_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "artifact_dir", tmp_path / "artifacts")
    client = TestClient(app_module.app)

    response = client.post("/admin/seed-demo-capabilities")
    assert response.status_code == 404


def test_run_events_404_for_unknown_run(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "evidence_dir", tmp_path / "evidence")
    client = TestClient(app_module.app)

    response = client.get("/runs/does-not-exist/events")
    assert response.status_code == 404


def test_run_events_returns_parsed_jsonl(monkeypatch, tmp_path):
    monkeypatch.setattr(global_settings, "evidence_dir", tmp_path / "evidence")
    run_dir = tmp_path / "evidence" / "runs" / "fake-run-id"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00Z", "event": "replay.started"}) + "\n",
        encoding="utf-8",
    )
    client = TestClient(app_module.app)

    response = client.get("/runs/fake-run-id/events")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "fake-run-id"
    assert body["events"] == [{"timestamp": "2026-01-01T00:00:00Z", "event": "replay.started"}]


@pytest.mark.e2e
def test_run_events_from_a_real_execute(monkeypatch, tmp_path):
    """The live version of the two unit tests above: a real execute produces a real run_id, and
    that run_id's real event trace is readable back over HTTP."""
    monkeypatch.setattr(global_settings, "evidence_dir", tmp_path / "evidence")
    client = TestClient(app_module.app)

    execute_response = client.post(
        "/capabilities/lookup-member-savings-balance.v1/execute",
        json={"inputs": {"memberId": "10002"}},
    )
    assert execute_response.status_code == 200
    run_id = execute_response.json()["run_id"]

    events_response = client.get(f"/runs/{run_id}/events")
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert len(events) > 0
    assert all("timestamp" in e and "event" in e for e in events)
