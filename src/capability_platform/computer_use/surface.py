from __future__ import annotations

from typing import Any, Protocol

from playwright.async_api import Browser, Page, async_playwright
from playwright.async_api import TimeoutError as _DriverTimeout

from capability_platform.models import Locator, Target


class SurfaceTimeout(Exception):
    """Raised by a SurfaceAdapter when an action doesn't complete within its own timeout — the
    adapter-agnostic signal ReplayEngine catches to classify a result as ErrorCategory.TIMEOUT,
    without replay.py ever needing to know which concrete driver raised it."""


class SurfaceAdapter(Protocol):
    """What ReplayEngine is allowed to depend on. A desktop/legacy-web adapter implements this
    same contract; ReplayEngine never reaches past it into a concrete driver (e.g. Playwright)."""

    async def start(self, url: str) -> Any: ...
    async def close(self) -> None: ...
    async def observe(self) -> dict[str, Any]: ...
    async def current_url(self) -> str: ...
    async def navigate(self, url: str) -> None: ...
    async def wait(self, ms: int) -> None: ...
    async def click(self, target: Target) -> None: ...
    async def type(self, target: Target, value: str) -> None: ...
    async def extract(self, target: Target) -> str: ...
    async def visible(self, target: Target) -> bool: ...
    async def value_of(self, target: Target) -> str | None: ...
    async def screenshot(self) -> bytes: ...


class PlaywrightSurface:
    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self._playwright: Any = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    async def start(self, url: str) -> PlaywrightSurface:
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()
        await self.page.goto(url, wait_until="domcontentloaded")
        return self

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def observe(self) -> dict[str, Any]:
        assert self.page
        snapshot = await self.page.locator("body").aria_snapshot()
        return {"url": self.page.url, "accessibility": snapshot[:15_000]}

    async def current_url(self) -> str:
        assert self.page
        return self.page.url

    async def navigate(self, url: str) -> None:
        assert self.page
        try:
            await self.page.goto(url)
        except _DriverTimeout as exc:
            raise SurfaceTimeout(str(exc)) from exc

    async def wait(self, ms: int) -> None:
        assert self.page
        await self.page.wait_for_timeout(ms)

    async def screenshot(self) -> bytes:
        assert self.page
        return await self.page.screenshot(full_page=True)

    def _locator(self, locator: Locator):
        assert self.page
        if locator.strategy == "role":
            return self.page.get_by_role(locator.value, name=locator.name, exact=locator.exact)
        if locator.strategy == "label":
            return self.page.get_by_label(locator.value, exact=locator.exact)
        if locator.strategy == "text":
            return self.page.get_by_text(locator.value, exact=locator.exact)
        if locator.strategy == "css":
            return self.page.locator(locator.value)
        if locator.strategy == "xpath":
            return self.page.locator(f"xpath={locator.value}")
        raise ValueError("Coordinate targets require a screenshot surface adapter")

    async def resolve(self, target: Target):
        errors: list[str] = []
        for candidate in [target.primary, *target.fallbacks]:
            try:
                located = self._locator(candidate)
                if await located.count() == 1 and await located.is_visible():
                    return located
                errors.append(
                    f"{candidate.strategy}:{candidate.value} matched {await located.count()}"
                )
            except Exception as exc:  # noqa: BLE001 - heterogeneous driver failures become fallback evidence
                errors.append(str(exc))
        raise LookupError("; ".join(errors))

    async def click(self, target: Target) -> None:
        located = await self.resolve(target)
        try:
            await located.click()
        except _DriverTimeout as exc:
            raise SurfaceTimeout(str(exc)) from exc

    async def type(self, target: Target, value: str) -> None:
        located = await self.resolve(target)
        try:
            await located.fill(value)
        except _DriverTimeout as exc:
            raise SurfaceTimeout(str(exc)) from exc

    async def extract(self, target: Target) -> str:
        return (await (await self.resolve(target)).inner_text()).strip()

    async def visible(self, target: Target) -> bool:
        try:
            return await (await self.resolve(target)).is_visible()
        except LookupError:
            return False

    async def value_of(self, target: Target) -> str | None:
        return await (await self.resolve(target)).input_value()
