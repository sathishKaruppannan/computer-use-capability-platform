"""Approval flow for risky/irreversible steps (T6). The PDF leaves the mechanism up to us
("block, require confirmation, or flag — your call"); this reuses the same same-session
intervention mechanism as an unexpected-condition handoff rather than inventing a second one:
pause before the risky step runs, a human approves or denies, resume, retry authorization."""

import asyncio
from pathlib import Path

import pytest

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.intervention.manager import interventions
from capability_platform.models import ErrorCategory, RiskLevel, RunStatus
from capability_platform.policy.engine import PolicyEngine, default_policy


def _artifact_with_risky_step():
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    modified = artifact.model_copy(deep=True)
    modified.steps[2].risk = RiskLevel.RISKY  # "click Open Accounts" — arbitrary choice for the test
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
async def test_approved_risky_step_completes(tmp_path):
    artifact = _artifact_with_risky_step()
    risky_step_id = artifact.steps[2].id
    before_ids = set(interventions.items)

    task = asyncio.create_task(
        ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
            artifact, {"memberId": "10002"}
        )
    )

    intervention_id = await _wait_for_new_intervention(before_ids)
    item = interventions.items[intervention_id]
    assert item.step_id == risky_step_id
    assert "requires human approval" in item.reason
    assert item.capability_id == artifact.qualified_id

    interventions.resume(intervention_id, approved=True)
    result = await task

    assert result.status == RunStatus.SUCCESS
    assert result.outputs["savingsBalance"] == 1220.0

    events = (tmp_path / "runs" / result.run_id / "events.jsonl").read_text(encoding="utf-8")
    assert '"event": "intervention.created"' in events
    assert '"approved": true' in events


@pytest.mark.e2e
async def test_denied_risky_step_fails_with_policy_error(tmp_path):
    artifact = _artifact_with_risky_step()
    before_ids = set(interventions.items)

    task = asyncio.create_task(
        ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
            artifact, {"memberId": "10002"}
        )
    )

    intervention_id = await _wait_for_new_intervention(before_ids)
    interventions.resume(intervention_id, approved=False)
    result = await task

    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.POLICY
    assert result.error.code == "APPROVAL_DENIED"
    assert result.error.evidence_path is not None
    assert Path(result.error.evidence_path).exists()
