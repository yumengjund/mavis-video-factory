"""V1.5.3 Browser Core - Playwright 浏览器自动化核心"""
import os
import json
import time
import random
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

class BrowserCore:
    def __init__(self, headless=True, proxy=None, user_agent=None):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")
        self.headless = headless
        self.proxy = proxy
        self.user_agent = user_agent or random.choice(_USER_AGENTS)
        self._playwright = sync_playwright().start()
        self._browser = None
        self._context = None

    def _ensure_browser(self):
        if self._browser is None:
            launch_args = {"headless": self.headless}
            if self.proxy:
                launch_args["proxy"] = {"server": self.proxy}
            self._browser = self._playwright.chromium.launch(**launch_args)
            context_args = {"user_agent": self.user_agent, "viewport": {"width": 1920, "height": 1080}}
            self._context = self._browser.new_context(**context_args)

    def new_page(self) -> "Page":
        self._ensure_browser()
        return self._context.new_page()

    def close(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._context = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
