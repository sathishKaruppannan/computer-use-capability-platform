"""Discovery must classify a step's risk itself — code-side, never left to the model — so that
a genuinely discovered mutating action (e.g. clicking 'Update' or 'Save') actually reaches
PolicyEngine's risk threshold instead of always coming back read_only. Real gap found and fixed:
agent/discovery.py used to hardcode risk=RiskLevel.READ_ONLY on every step regardless of what it
did, so the approval gate built for T6 could never trigger from real discovery output."""

import asyncio
from pathlib import Path

import pytest

from capability_platform.agent.discovery import ClaudeDiscoveryAgent
from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.intervention.manager import interventions
from capability_platform.models import ActionType, Locator, RiskLevel, Target
from capability_platform.policy.engine import PolicyEngine, default_policy


def _target(name: str | None = None, value: str | None = None) -> Target:
    return Target(
        primary=Locator(strategy="role", value=value or "button", name=name),
        rationale="test",
    )


@pytest.mark.parametrize(
    ("action", "target", "expected"),
    [
        (ActionType.CLICK, _target(name="Search"), RiskLevel.READ_ONLY),
        (ActionType.CLICK, _target(name="Open Accounts"), RiskLevel.READ_ONLY),
        (ActionType.CLICK, _target(name="Save"), RiskLevel.RISKY),
        (ActionType.CLICK, _target(name="Update Phone Number"), RiskLevel.RISKY),
        (ActionType.CLICK, _target(name="Delete Account"), RiskLevel.RISKY),
        (ActionType.CLICK, _target(name="Confirm Transfer"), RiskLevel.RISKY),
        (ActionType.TYPE, _target(name="Phone Number"), RiskLevel.REVERSIBLE),
        (ActionType.SELECT, _target(name="Account Type"), RiskLevel.REVERSIBLE),
        (ActionType.EXTRACT, _target(name="Balance"), RiskLevel.READ_ONLY),
        (ActionType.WAIT, None, RiskLevel.READ_ONLY),
        (ActionType.NAVIGATE, None, RiskLevel.READ_ONLY),
    ],
)
def test_classify_risk(action, target, expected):
    assert ClaudeDiscoveryAgent._classify_risk(action, target) == expected


@pytest.mark.e2e
async def test_a_discovery_classified_risky_step_triggers_the_real_approval_gate(tmp_path):
    """Closes the loop for real: take the exact classification discovery would produce for a
    mutating click, put it on a step, and confirm ReplayEngine's approval gate (T6) actually
    fires for it — not just that the classifier function returns the right enum value."""
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    modified = artifact.model_copy(deep=True)
    mutating_step = modified.steps[2]
    mutating_step.risk = ClaudeDiscoveryAgent._classify_risk(
        mutating_step.action, _target(name="Update Phone Number")
    )
    assert mutating_step.risk == RiskLevel.RISKY  # sanity: this is what discovery would produce

    before_ids = set(interventions.items)
    task = asyncio.create_task(
        ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
            modified, {"memberId": "10002"}
        )
    )

    elapsed = 0.0
    intervention_id = None
    while elapsed < 5.0:
        new_ids = set(interventions.items) - before_ids
        if new_ids:
            intervention_id = next(iter(new_ids))
            break
        await asyncio.sleep(0.05)
        elapsed += 0.05
    assert intervention_id is not None, "risky step did not pause for approval"

    interventions.resume(intervention_id, approved=True)
    result = await task
    assert result.outputs["savingsBalance"] == 1220.0
