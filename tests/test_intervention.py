"""Same-session human-in-the-loop handoff: pause on an injected unexpected dialog, let a
human (here, the test itself) resolve it on the SAME live page, resume, and complete replay
with no LLM involved. Requires the live demo app (member 10003 always shows an interstitial)."""

import asyncio
from pathlib import Path

import pytest

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.intervention.manager import ControlOwner, interventions
from capability_platform.models import (
    Checkpoint,
    ErrorCategory,
    ErrorRule,
    Locator,
    RunStatus,
    Target,
)
from capability_platform.policy.engine import PolicyEngine, default_policy


def _artifact_with_interstitial_pause():
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    modified = artifact.model_copy(deep=True)
    search_step = modified.steps[1]
    search_step.errors.append(
        ErrorRule(
            code="SESSION_INTERSTITIAL",
            category=ErrorCategory.RECOVERABLE,
            when=Checkpoint(
                kind="visible",
                target=Target(
                    primary=Locator(strategy="text", value="Session Notice", exact=False),
                    rationale="Injected unexpected interstitial for handoff testing",
                ),
            ),
            message="Unexpected session interstitial requires human dismissal",
            recovery="pause",
        )
    )
    return modified


async def _wait_for_new_intervention(before_ids: set[str], timeout: float = 5.0) -> str:
    elapsed = 0.0
    while elapsed < timeout:
        new_ids = set(interventions.items) - before_ids
        if new_ids:
            return next(iter(new_ids))
        await asyncio.sleep(0.05)
        elapsed += 0.05
    raise AssertionError("intervention was not created within timeout")


@pytest.mark.e2e
async def test_human_dismisses_interstitial_and_replay_completes(tmp_path):
    artifact = _artifact_with_interstitial_pause()
    before_ids = set(interventions.items)

    task = asyncio.create_task(
        ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
            artifact, {"memberId": "10003"}
        )
    )

    intervention_id = await _wait_for_new_intervention(before_ids)
    item = interventions.items[intervention_id]

    # Intervention carries full context: run, capability, step, reason, state, screenshot.
    assert item.run_id
    assert item.capability_id == artifact.qualified_id
    assert item.step_id == artifact.steps[1].id
    assert item.reason
    assert item.state
    assert item.screenshot and Path(item.screenshot).exists()
    # Control has transferred to the human.
    assert item.owner == ControlOwner.HUMAN

    # Same live page — not a new browser session — for the human to act on.
    page = interventions.get_page(intervention_id)
    assert page is not None
    assert page.url  # the same page that was mid-flow, not a fresh blank page
    await page.get_by_role("button", name="Continue").click()

    # Resume signal.
    interventions.resume(intervention_id)

    # Ownership transferred back; deterministic replay completes with no LLM involved.
    result = await task
    assert result.status == RunStatus.SUCCESS
    assert result.outputs["savingsBalance"] == 875.50

    # All control-transfer events recorded in the same run trace.
    events = (tmp_path / "runs" / result.run_id / "events.jsonl").read_text(encoding="utf-8")
    for expected in (
        '"event": "intervention.created"',
        '"owner": "human"',
        '"owner": "automation"',
        '"event": "resume.observed"',
        '"event": "resume.validated"',
    ):
        assert expected in events


@pytest.mark.e2e
async def test_resume_without_resolving_interstitial_fails_hard(tmp_path):
    """Resuming without actually dismissing the condition must not be silently accepted."""
    artifact = _artifact_with_interstitial_pause()
    before_ids = set(interventions.items)

    task = asyncio.create_task(
        ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
            artifact, {"memberId": "10003"}
        )
    )

    intervention_id = await _wait_for_new_intervention(before_ids)
    interventions.resume(intervention_id)  # resume WITHOUT dismissing the dialog first

    result = await task
    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.CHECKPOINT
    assert "not resolved" in result.error.message
