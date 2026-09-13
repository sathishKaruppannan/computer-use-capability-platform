"""Input-contract validation happens before any browser is launched (no live app needed)."""

from pathlib import Path

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.models import ErrorCategory, ExecutionResult, RunStatus
from capability_platform.policy.engine import PolicyEngine, default_policy

ARTIFACT = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")


async def _run(inputs: dict, tmp_path) -> ExecutionResult:
    return await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        ARTIFACT, inputs
    )


async def test_missing_required_input_fails_before_browser(tmp_path):
    result = await _run({}, tmp_path)
    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.VALIDATION
    assert result.error.code == "MISSING_INPUT"


async def test_input_not_matching_pattern_fails_before_browser(tmp_path):
    result = await _run({"memberId": "abc"}, tmp_path)
    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.VALIDATION
    assert result.error.code == "INVALID_INPUT"
