from pathlib import Path

import pytest

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.models import ErrorCategory, RunStatus
from capability_platform.policy.engine import PolicyEngine, default_policy


def _load_artifact():
    return ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")


@pytest.mark.e2e
async def test_replay_success(tmp_path):
    """Run with the demo app already listening on port 8001."""
    artifact = _load_artifact()
    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        artifact, {"memberId": "10002"}
    )
    assert result.status == RunStatus.SUCCESS
    assert result.outputs["savingsBalance"] == 1220.0
    assert isinstance(result.outputs["savingsBalance"], float)
    declared_type = next(o for o in artifact.outputs if o.name == "savingsBalance").type
    assert declared_type == "number"


@pytest.mark.e2e
async def test_replay_business_outcome_member_not_found(tmp_path):
    """A member that doesn't exist is a business outcome, not a crash."""
    artifact = _load_artifact()
    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        artifact, {"memberId": "99999"}
    )
    assert result.status == RunStatus.BUSINESS_OUTCOME
    assert result.business_code == "MEMBER_NOT_FOUND"
    assert result.error is None


@pytest.mark.e2e
async def test_replay_structured_failure_on_broken_locator(tmp_path):
    """An unresolvable target produces a structured hard failure with step id + screenshot."""
    artifact = _load_artifact()
    broken = artifact.model_copy(deep=True)
    first_step_id = broken.steps[0].id
    broken.steps[0].target.primary.value = "Nonexistent Label That Does Not Exist"
    broken.steps[0].target.fallbacks = []
    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        broken, {"memberId": "10002"}
    )
    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.CHECKPOINT
    assert result.error.step_id == first_step_id
    assert result.error.evidence_path is not None
    assert Path(result.error.evidence_path).exists()


@pytest.mark.e2e
async def test_replay_never_instantiates_llm_client(tmp_path, monkeypatch):
    """Replay must not instantiate or call an LLM client, even indirectly."""
    import anthropic

    def _forbidden(*args, **kwargs):
        raise AssertionError("replay must never instantiate an LLM client")

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _forbidden)
    monkeypatch.setattr(anthropic, "Anthropic", _forbidden)

    artifact = _load_artifact()
    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        artifact, {"memberId": "10002"}
    )
    assert result.status == RunStatus.SUCCESS
    assert result.outputs["savingsBalance"] == 1220.0
