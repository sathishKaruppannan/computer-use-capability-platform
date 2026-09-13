"""Unapproved/blocked capabilities must not be exposed or invocable via agent-facing surfaces
(REST here; MCP shares the same ArtifactStore.list_approved()/lifecycle-gate logic). No live
browser needed — draft capabilities are rejected before replay ever starts."""

from fastapi.testclient import TestClient

from capability_platform.api import app as app_module
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.models import (
    ApplicationBinding,
    CapabilityArtifact,
    Checkpoint,
    Locator,
    OutputSpec,
    ParameterSpec,
    Target,
)
from capability_platform.settings import settings as global_settings


def _minimal_artifact(id_: str, lifecycle: str) -> CapabilityArtifact:
    return CapabilityArtifact(
        id=id_,
        name="Test capability",
        description="test",
        lifecycle=lifecycle,
        application=ApplicationBinding(
            vendor="x", product="y", base_url="http://127.0.0.1:8001"
        ),
        inputs=[ParameterSpec(name="memberId", type="string", description="x")],
        outputs=[OutputSpec(name="out", type="string", description="x")],
        steps=[],
        success=Checkpoint(
            kind="visible",
            target=Target(primary=Locator(strategy="text", value="x"), rationale="x"),
        ),
        discovered_by="test",
    )


def test_draft_capability_not_listed_or_executable_via_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(global_settings, "artifact_dir", tmp_path)
    store = ArtifactStore(tmp_path)
    store.save(_minimal_artifact("draft-cap", "draft"))
    store.save(_minimal_artifact("approved-cap", "approved"))

    client = TestClient(app_module.app)

    listed_ids = {c["id"] for c in client.get("/capabilities").json()}
    assert "approved-cap.v1" in listed_ids
    assert "draft-cap.v1" not in listed_ids

    response = client.post("/capabilities/draft-cap.v1/execute", json={"inputs": {}})
    assert response.status_code == 403


def test_store_list_approved_filters_by_lifecycle(tmp_path):
    store = ArtifactStore(tmp_path)
    store.save(_minimal_artifact("draft-cap", "draft"))
    store.save(_minimal_artifact("approved-cap", "approved"))
    store.save(_minimal_artifact("active-cap", "active"))
    store.save(_minimal_artifact("deprecated-cap", "deprecated"))

    approved_ids = {a.qualified_id for a in store.list_approved()}
    assert approved_ids == {"approved-cap.v1", "active-cap.v1"}
    assert len(store.list()) == 4
