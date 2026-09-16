import json
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from capability_platform.api.admin import ADMIN_HTML
from capability_platform.api.v1_routes import router as v1_router
from capability_platform.capabilities.demo_seed import build_approval_demo, build_pause_demo
from capability_platform.capabilities.store import AGENT_EXPOSABLE_LIFECYCLES
from capability_platform.intervention.manager import ControlOwner, interventions
from capability_platform.runtime import discovery_agent, replay_engine, store
from capability_platform.settings import settings

app = FastAPI(title="Computer-Use Capability Platform", version="0.1.0")
app.include_router(v1_router)


class DiscoveryRequest(BaseModel):
    goal: str
    target_url: str | None = None
    example_member_id: str = "10001"


class ExecuteRequest(BaseModel):
    inputs: dict[str, Any]


class ResumeRequest(BaseModel):
    # Only meaningful for an approval-gated pause (risky/irreversible step); ignored otherwise.
    approved: bool | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/capabilities")
def list_capabilities():
    return [
        {"id": item.qualified_id, "name": item.name, "inputs": item.inputs, "outputs": item.outputs}
        for item in store().list_approved()
    ]


@app.post("/discover")
async def discover(request: DiscoveryRequest):
    artifact = await discovery_agent().discover(
        request.goal, request.target_url or settings.target_url, request.example_member_id
    )
    path = store().save(artifact)
    return {"artifact": artifact, "path": str(path)}


@app.post("/capabilities/{capability_id}/execute")
async def execute(capability_id: str, request: ExecuteRequest):
    try:
        artifact = store().load(capability_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Capability not found") from exc
    if artifact.lifecycle not in AGENT_EXPOSABLE_LIFECYCLES:
        raise HTTPException(403, f"Capability '{capability_id}' is not approved for invocation")
    return await replay_engine().execute(artifact, request.inputs)


@app.get("/interventions")
def list_interventions(pending: bool = False):
    items = list(interventions.items.values())
    if pending:
        # GET /interventions never forgets a resolved one (it's the audit trail) — this filters
        # to only what's actually still awaiting a human, by control ownership rather than by
        # guessing from `reason` text.
        items = [item for item in items if item.owner == ControlOwner.HUMAN]
    return items


@app.get("/interventions/{intervention_id}/screenshot")
def intervention_screenshot(intervention_id: str):
    try:
        item = interventions.items[intervention_id]
    except KeyError as exc:
        raise HTTPException(404, "Intervention not found") from exc
    if not item.screenshot or not Path(item.screenshot).exists():
        raise HTTPException(404, "No screenshot recorded for this intervention")
    return FileResponse(item.screenshot, media_type="image/png")


@app.post("/interventions/{intervention_id}/resume")
def resume(
    intervention_id: str,
    request: ResumeRequest | None = Body(default=None),  # noqa: B008 - FastAPI's own idiom
):
    try:
        return interventions.resume(
            intervention_id, approved=request.approved if request else None
        )
    except KeyError as exc:
        raise HTTPException(404, "Intervention not found") from exc


@app.get("/runs/{run_id}/events")
def run_events(run_id: str):
    """Reads back evidence/runs/{run_id}/events.jsonl — the append-only, already-redacted
    (Redactor.clean(), observability/evidence.py) event log EvidenceCollector.event() wrote
    during discovery/replay. Powers the admin console's Observability section, including the
    same-session `page_identity` before/after-resume proof. Local-demo-only, unauthenticated —
    like /interventions, this isn't part of the versioned /v1 client contract."""
    log_path = settings.evidence_dir / "runs" / run_id / "events.jsonl"
    if not log_path.exists():
        raise HTTPException(404, "No evidence found for this run_id")
    events = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {"run_id": run_id, "events": events}


@app.post("/admin/seed-demo-capabilities")
def seed_demo_capabilities():
    """One-click equivalent of running scripts/debug/create_pause_demo_capability.py and
    create_approval_demo_capability.py by hand — builds and saves both intervention-flow demo
    capabilities so the pause/approval demos are reachable with no terminal step. Idempotent:
    ArtifactStore.save() overwrites by qualified_id. Local-demo-only, unauthenticated, matching
    /admin's own trust model."""
    artifact_store = store()
    try:
        pause_demo = build_pause_demo(artifact_store)
        approval_demo = build_approval_demo(artifact_store)
    except FileNotFoundError as exc:
        raise HTTPException(
            404,
            "Base capability 'lookup-member-savings-balance.v1' not found — run discovery "
            "once first (Client initiate section)",
        ) from exc
    artifact_store.save(pause_demo)
    artifact_store.save(approval_demo)
    return {"seeded": [pause_demo.qualified_id, approval_demo.qualified_id]}


@app.post("/admin/reset-to-draft/{capability_id}")
def reset_to_draft(capability_id: str):
    """Demo helper: flips an already-approved capability back to lifecycle="draft" with no
    Claude call, so the pending-artifacts/review/approve flow (§2 in the dashboard) can be
    demoed repeatedly and instantly instead of waiting ~30-60s and spending a real API call on
    /v1/discover every time you want to show it again. Local-demo-only, unauthenticated,
    matching /admin's own trust model."""
    try:
        artifact = store().load(capability_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "Capability not found") from exc
    artifact.lifecycle = "draft"
    store().save(artifact)
    return {"capability_id": artifact.qualified_id, "lifecycle": artifact.lifecycle}


@app.get("/admin", response_class=HTMLResponse)
def admin_console():
    """A local admin console for the pending-capabilities and pending-interventions queues —
    same-origin fetch() calls straight to this app's own REST routes, so it works with no build
    step and no CORS setup. Deliberately not a Claude Artifact: an Artifact runs in a sandboxed
    browser on claude.ai and can't reach this machine's 127.0.0.1. Open at
    http://127.0.0.1:8000/admin once `make platform` is running."""
    return HTMLResponse(ADMIN_HTML)
