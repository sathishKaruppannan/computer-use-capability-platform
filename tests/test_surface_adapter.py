"""Proves the SurfaceAdapter seam is real, not just declared (T18): ReplayEngine runs a full
capability against a fake, in-memory adapter with zero Playwright involvement, standing in for
a hypothetical desktop/legacy-web driver. No browser, no e2e marker needed."""

from capability_platform.computer_use.replay import ReplayEngine
from capability_platform.models import (
    ActionType,
    ApplicationBinding,
    CapabilityArtifact,
    Checkpoint,
    Locator,
    OutputSpec,
    ParameterSpec,
    RunStatus,
    Step,
    Target,
)
from capability_platform.policy.engine import PolicyEngine, default_policy


class FakeSurface:
    """A SurfaceAdapter with no Playwright import anywhere — a minimal stand-in for what a
    desktop/legacy-web adapter would look like. Locator `.value` doubles as an arbitrary key
    into this fake app's state, since there's no real DOM to query."""

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self.fields: dict[str, str] = {}
        self.current_page_url = ""
        self.visible_texts: set[str] = set()

    async def start(self, url: str) -> "FakeSurface":
        self.current_page_url = url
        return self

    async def close(self) -> None:
        pass

    async def observe(self) -> dict:
        return {"url": self.current_page_url, "accessibility": "fake"}

    async def current_url(self) -> str:
        return self.current_page_url

    async def navigate(self, url: str) -> None:
        self.current_page_url = url

    async def wait(self, ms: int) -> None:
        pass

    async def click(self, target: Target) -> None:
        if target.primary.value == "Search":
            self.visible_texts.add("Balance Screen")

    async def type(self, target: Target, value: str) -> None:
        self.fields[target.primary.value] = value

    async def extract(self, target: Target) -> str:
        return "$1234.56"

    async def visible(self, target: Target) -> bool:
        return target.primary.value in self.visible_texts

    async def value_of(self, target: Target) -> str | None:
        return self.fields.get(target.primary.value)

    async def screenshot(self) -> bytes:
        return b"fake-png-bytes"


def _text_target(value: str) -> Target:
    return Target(primary=Locator(strategy="text", value=value), rationale="fake adapter test")


def _fake_artifact() -> CapabilityArtifact:
    return CapabilityArtifact(
        id="fake-lookup",
        name="Fake lookup",
        description="Exercises ReplayEngine against a non-Playwright SurfaceAdapter",
        lifecycle="approved",
        application=ApplicationBinding(
            vendor="Test", product="FakeApp", base_url="http://127.0.0.1/fake-app"
        ),
        inputs=[ParameterSpec(name="memberId", type="string", description="id")],
        outputs=[OutputSpec(name="balance", type="number", description="balance")],
        steps=[
            Step(
                id="type-id",
                action=ActionType.TYPE,
                description="type member id",
                target=_text_target("memberId"),
                value="{{memberId}}",
            ),
            Step(
                id="click-search",
                action=ActionType.CLICK,
                description="click search",
                target=_text_target("Search"),
                checkpoint=Checkpoint(kind="visible", target=_text_target("Balance Screen")),
            ),
            Step(
                id="extract-balance",
                action=ActionType.EXTRACT,
                description="extract balance",
                output="balance",
                target=_text_target("balance-field"),
            ),
        ],
        success=Checkpoint(kind="visible", target=_text_target("Balance Screen")),
        discovered_by="test",
    )


async def test_replay_engine_works_with_a_non_playwright_surface_adapter(tmp_path):
    artifact = _fake_artifact()
    engine = ReplayEngine(
        PolicyEngine(default_policy()), tmp_path, surface_factory=lambda headless: FakeSurface(headless)
    )
    result = await engine.execute(artifact, {"memberId": "99999"})

    assert result.status == RunStatus.SUCCESS
    assert result.outputs["balance"] == 1234.56
