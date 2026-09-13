from pathlib import Path

import pytest

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.models import RunStatus
from capability_platform.policy.engine import PolicyEngine, default_policy


@pytest.mark.e2e
async def test_replay_success(tmp_path):
    """Run with the demo app already listening on port 8001."""
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        artifact, {"memberId": "10002"}
    )
    assert result.status == RunStatus.SUCCESS
    assert result.outputs["savingsBalance"] == 1220.0
