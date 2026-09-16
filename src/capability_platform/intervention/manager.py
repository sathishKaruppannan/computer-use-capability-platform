import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class ControlOwner(StrEnum):
    AUTOMATION = "automation"
    HUMAN = "human"


class Intervention(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    capability_id: str | None = None
    reason: str
    step_id: str | None = None
    screenshot: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    owner: ControlOwner = ControlOwner.HUMAN
    # "approval": a risky/irreversible step awaiting an explicit approve/deny decision.
    # "pause": an unexpected condition (e.g. an interstitial) awaiting dismissal — approval
    # isn't a concept here, resuming is enough. Lets a UI show the right action(s) without
    # having to parse `reason` text.
    kind: Literal["pause", "approval"] = "pause"
    # Only meaningful when kind == "approval"; None for a plain pause/dismiss handoff.
    approved: bool | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InterventionManager:
    """In-process handoff that preserves the live Playwright session."""

    def __init__(self) -> None:
        self.items: dict[str, Intervention] = {}
        self._resume: dict[str, asyncio.Event] = {}
        # Live Playwright Page handles, kept in-process only — never part of the Pydantic
        # model or any API/evidence payload. This is what makes the handoff same-session: a
        # same-process operator adapter (or, in this POC, a test standing in for a human) can
        # fetch the exact page the paused run is using and act on it before resuming.
        self._pages: dict[str, Any] = {}

    def create(self, run_id: str, reason: str, *, page: Any = None, **context: Any) -> Intervention:
        item = Intervention(run_id=run_id, reason=reason, **context)
        self.items[item.id] = item
        self._resume[item.id] = asyncio.Event()
        if page is not None:
            self._pages[item.id] = page
        return item

    def get_page(self, intervention_id: str) -> Any:
        """The live Page for this intervention, if any — the same session, not a new one."""
        return self._pages.get(intervention_id)

    async def wait_for_resume(self, intervention_id: str) -> None:
        await self._resume[intervention_id].wait()

    async def wait_for_approval(self, intervention_id: str) -> bool:
        """Like wait_for_resume, but returns the human's approve/deny decision."""
        await self.wait_for_resume(intervention_id)
        return self.items[intervention_id].approved is True

    def resume(self, intervention_id: str, *, approved: bool | None = None) -> Intervention:
        item = self.items[intervention_id]
        item.owner = ControlOwner.AUTOMATION
        if approved is not None:
            item.approved = approved
        self._resume[intervention_id].set()
        self._pages.pop(intervention_id, None)
        return item


interventions = InterventionManager()
