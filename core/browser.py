"""Playwright browser lifecycle and page manager."""

import asyncio
from typing import AsyncGenerator, Optional
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from config import config
from utils.logger import log


class BrowserManager:
    """Manages Playwright browser lifecycle and stealth configurations."""

    def __init__(self, headless: Optional[bool] = None, slow_mo: Optional[int] = None):
        self.headless = headless if headless is not None else config.HEADLESS
        self.slow_mo = slow_mo if slow_mo is not None else config.SLOW_MO_MS
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> Page:
        """Launch browser and configure context."""
        log.info(f"Launching Playwright Chromium (headless={self.headless}, slow_mo={self.slow_mo}ms)...")
        self._playwright = await async_playwright().start()

        # Launch chromium with anti-bot/stealth flags and user agent
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--window-size=1280,800",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        self._page = await self._context.new_page()
        # Set default navigation timeout
        self._page.set_default_timeout(30000)
        self._page.set_default_navigation_timeout(30000)

        return self._page

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not started. Call await browser_manager.start() first.")
        return self._page

    async def close(self) -> None:
        """Gracefully close browser and playwright instances."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("Browser session closed.")


async def get_browser_context(headless: Optional[bool] = None) -> AsyncGenerator[Page, None]:
    """Async context manager helper for browser sessions."""
    manager = BrowserManager(headless=headless)
    page = await manager.start()
    try:
        yield page
    finally:
        await manager.close()
