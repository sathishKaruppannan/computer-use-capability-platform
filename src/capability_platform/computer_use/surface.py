from __future__ import annotations

from typing import Any, Protocol

from playwright.async_api import Browser, Page, async_playwright

from capability_platform.models import Locator, Target


class SurfaceAdapter(Protocol):
    async def observe(self) -> dict[str, Any]: ...
    async def click(self, target: Target) -> None: ...
    async def type(self, target: Target, value: str) -> None: ...
    async def extract(self, target: Target) -> str: ...


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
        await (await self.resolve(target)).click()

    async def type(self, target: Target, value: str) -> None:
        await (await self.resolve(target)).fill(value)

    async def extract(self, target: Target) -> str:
        return (await (await self.resolve(target)).inner_text()).strip()

    async def visible(self, target: Target) -> bool:
        try:
            return await (await self.resolve(target)).is_visible()
        except LookupError:
            return False
