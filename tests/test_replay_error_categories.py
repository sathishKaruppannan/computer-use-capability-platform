"""Two error categories that used to be declared in the schema but never assigned anywhere in
replay.py (found by direct inspection, the same class of gap as the earlier dead RECOVERABLE
enum member): AUTH (a declared error rule with a non-business, non-retry, non-pause recovery
used to collapse into the generic 'checkpoint_failed' bucket, losing its own category) and
TIMEOUT (a driver-level action timeout had no distinct classification at all)."""

from pathlib import Path

import pytest

from capability_platform.capabilities.store import ArtifactStore
from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.computer_use.surface import SurfaceTimeout
from capability_platform.models import (
    Checkpoint,
    ErrorCategory,
    ErrorRule,
    Locator,
    RunStatus,
    Target,
)
from capability_platform.policy.engine import PolicyEngine, default_policy


@pytest.mark.e2e
async def test_declared_auth_error_rule_keeps_its_own_category(tmp_path):
    """A real session-expired state (demo_app.py member 10005) must fail as ErrorCategory.AUTH,
    not be silently renamed to the generic checkpoint_failed bucket."""
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    modified = artifact.model_copy(deep=True)
    modified.steps[1].errors.append(
        ErrorRule(
            code="SESSION_EXPIRED",
            category=ErrorCategory.AUTH,
            when=Checkpoint(
                kind="visible",
                target=Target(
                    primary=Locator(strategy="text", value="Session expired", exact=False),
                    rationale="Explicit application auth failure",
                ),
            ),
            message="The session expired mid-flow and must be re-authenticated",
            recovery="return",
        )
    )

    result = await ReplayEngine(PolicyEngine(default_policy()), tmp_path, True).execute(
        modified, {"memberId": "10005"}
    )

    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.AUTH
    assert result.error.code == "SESSION_EXPIRED"
    assert result.error.evidence_path is not None
    assert Path(result.error.evidence_path).exists()


class _TimeoutSurface:
    """A minimal SurfaceAdapter whose click() always times out — proves ReplayEngine classifies
    a driver-level timeout as ErrorCategory.TIMEOUT, without needing a real slow page."""

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless

    async def start(self, url: str):
        return self

    async def close(self) -> None:
        pass

    async def observe(self) -> dict:
        return {"url": "http://fake", "accessibility": "fake"}

    async def current_url(self) -> str:
        return "http://fake"

    async def navigate(self, url: str) -> None:
        pass

    async def wait(self, ms: int) -> None:
        pass

    async def click(self, target: Target) -> None:
        raise SurfaceTimeout("Timeout 500ms exceeded waiting for element to be clickable")

    async def type(self, target: Target, value: str) -> None:
        pass

    async def extract(self, target: Target) -> str:
        return "$0.00"

    async def visible(self, target: Target) -> bool:
        return False

    async def value_of(self, target: Target) -> str | None:
        return None

    async def screenshot(self) -> bytes:
        return b"fake-png-bytes"


async def test_driver_timeout_is_classified_as_timeout_not_checkpoint(tmp_path):
    artifact = ArtifactStore(Path("artifacts")).load("lookup-member-savings-balance.v1")
    engine = ReplayEngine(
        PolicyEngine(default_policy()), tmp_path, surface_factory=lambda headless: _TimeoutSurface(headless)
    )
    result = await engine.execute(artifact, {"memberId": "10002"})

    assert result.status == RunStatus.FAILURE
    assert result.error is not None
    assert result.error.category == ErrorCategory.TIMEOUT
    assert result.error.code == "ACTION_TIMEOUT"
