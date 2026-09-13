"""Automated wait/retry recovery for a transient condition (PDF glossary's own example) — no
human involved, unlike the pause/handoff path in test_intervention.py."""

from pathlib import Path

import pytest

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.models import (
    Checkpoint,
    ErrorCategory,
    ErrorRule,
    Locator,
    RunStatus,
    Target,
)
from capability_platform.policy.engine import PolicyEngine, default_policy


def _artifact_with_transient_load_retry(max_retries: int):
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    modified = artifact.model_copy(deep=True)
    modified.steps[1].errors.append(
        ErrorRule(
            code="TRANSIENT_LOAD",
            category=ErrorCategory.RECOVERABLE,
            when=Checkpoint(
                kind="visible",
                target=Target(
                    primary=Locator(
                        strategy="text", value="Loading member details", exact=False
                    ),
                    rationale="Injected transient load banner for retry-recovery testing",
                ),
            ),
            message="Member details are still loading",
            recovery="retry",
            max_retries=max_retries,
        )
    )
    return modified


@pytest.mark.e2e
async def test_transient_condition_clears_within_retry_budget(tmp_path):
    # Banner clears at 1200ms; 5 retries * 500ms = 2500ms budget, comfortably enough.
    artifact = _artifact_with_transient_load_retry(max_retries=5)
    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        artifact, {"memberId": "10004"}
    )
    assert result.status == RunStatus.SUCCESS
    assert result.outputs["savingsBalance"] == 3300.0

    events = (tmp_path / "runs" / result.run_id / "events.jsonl").read_text(encoding="utf-8")
    assert '"event": "recoverable.retry"' in events
    assert '"event": "recoverable.resolved"' in events


@pytest.mark.e2e
async def test_transient_condition_exhausting_retries_fails_hard(tmp_path):
    # Banner clears at 1200ms; 1 retry * 500ms = 500ms budget, deliberately not enough.
    artifact = _artifact_with_transient_load_retry(max_retries=1)
    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        artifact, {"memberId": "10004"}
    )
    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.CHECKPOINT
    assert "did not clear" in result.error.message
