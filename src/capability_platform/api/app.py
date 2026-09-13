from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from capability_platform.intervention.manager import interventions
from capability_platform.runtime import discovery_agent, replay_engine, store
from capability_platform.settings import settings

app = FastAPI(title="Computer-Use Capability Platform", version="0.1.0")


class DiscoveryRequest(BaseModel):
    goal: str
    target_url: str | None = None
    example_member_id: str = "10001"


class ExecuteRequest(BaseModel):
    inputs: dict[str, Any]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/capabilities")
def list_capabilities():
    return [
        {"id": item.qualified_id, "name": item.name, "inputs": item.inputs, "outputs": item.outputs}
        for item in store().list()
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
    return await replay_engine().execute(artifact, request.inputs)


@app.get("/interventions")
def list_interventions():
    return list(interventions.items.values())


@app.post("/interventions/{intervention_id}/resume")
def resume(intervention_id: str):
    try:
        return interventions.resume(intervention_id)
    except KeyError as exc:
        raise HTTPException(404, "Intervention not found") from exc
