import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ControlOwner(StrEnum):
    AUTOMATION = "automation"
    HUMAN = "human"


class Intervention(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    reason: str
    step_id: str | None = None
    screenshot: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    owner: ControlOwner = ControlOwner.HUMAN
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InterventionManager:
    """In-process handoff that preserves the live Playwright session."""

    def __init__(self) -> None:
        self.items: dict[str, Intervention] = {}
        self._resume: dict[str, asyncio.Event] = {}

    def create(self, run_id: str, reason: str, **context: Any) -> Intervention:
        item = Intervention(run_id=run_id, reason=reason, **context)
        self.items[item.id] = item
        self._resume[item.id] = asyncio.Event()
        return item

    async def wait_for_resume(self, intervention_id: str) -> None:
        await self._resume[intervention_id].wait()

    def resume(self, intervention_id: str) -> Intervention:
        item = self.items[intervention_id]
        item.owner = ControlOwner.AUTOMATION
        self._resume[intervention_id].set()
        return item


interventions = InterventionManager()
