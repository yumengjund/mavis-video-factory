"""V1.5.3 Persistent Browser Factory — 平台专属持久化浏览器上下文"""
import os
import json
import shutil
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# 平台专属指纹配置
_PLATFORM_FINGERPRINTS = {
    "douyin": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
    },
    "xiaohongshu": {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 390, "height": 844},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
    },
    "bilibili": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
    },
    "weibo": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
    },
}


class PersistentBrowserFactory:
    """为每个平台创建持久化浏览器上下文，通过 Playwright storage_state 机制复用会话。

    注意：此模块是 BrowserCore 的扩展层，不改动 browser_core.py。
    """

    def __init__(self, profile_root):
        """
        Args:
            profile_root: 浏览器 profile 根目录，每个平台会在此下创建子目录
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed.")
        self.profile_root = Path(profile_root)
        self.profile_root.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._browser = None
        self._contexts = {}  # platform → BrowserContext

    def get_profile_dir(self, platform):
        """获取平台专属 profile 目录路径。"""
        profile_dir = self.profile_root / platform
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir

    def _ensure_browser(self):
        """确保 Chromium 浏览器已启动。"""
        if self._browser is None:
            self._browser = self._playwright.chromium.launch(headless=True)

    def create_context(self, platform, headless=True):
        """为指定平台创建持久化浏览器上下文。

        使用 Playwright 的 launch_persistent_context 实现，
        该 API 自动将 cookies/localStorage/sessionStorage 持久化到 user_data_dir。

        Args:
            platform: 平台名
            headless: 是否无头模式

        Returns:
            (BrowserContext, Page) 元组
        """
        profile_dir = self.get_profile_dir(platform)
        fingerprint = _PLATFORM_FINGERPRINTS.get(platform,
                                                  _PLATFORM_FINGERPRINTS["bilibili"])

        context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            user_agent=fingerprint["user_agent"],
            viewport=fingerprint["viewport"],
            locale=fingerprint["locale"],
            timezone_id=fingerprint["timezone_id"],
        )
        self._contexts[platform] = context
        page = context.pages[0] if context.pages else context.new_page()
        return context, page

    def save_storage_state(self, platform):
        """将当前平台上下文的 storage state 保存到文件。"""
        if platform not in self._contexts:
            return None
        state_path = self.get_profile_dir(platform) / "storage_state.json"
        self._contexts[platform].storage_state(path=str(state_path))
        return str(state_path)

    def load_storage_state(self, platform):
        """从文件加载 storage state。返回 dict 或 None。"""
        state_path = self.get_profile_dir(platform) / "storage_state.json"
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def clear_profile(self, platform):
        """清除指定平台的浏览器 profile 数据。"""
        profile_dir = self.get_profile_dir(platform)
        # 关闭已有上下文
        if platform in self._contexts:
            try:
                self._contexts[platform].close()
            except Exception:
                pass
            del self._contexts[platform]
        # 删除 profile 目录
        if profile_dir.exists():
            shutil.rmtree(str(profile_dir))

    def close_platform(self, platform):
        """关闭指定平台的浏览器上下文。"""
        if platform in self._contexts:
            try:
                self._contexts[platform].close()
            except Exception:
                pass
            del self._contexts[platform]

    def close_all(self):
        """关闭所有浏览器上下文和浏览器实例。"""
        for platform in list(self._contexts.keys()):
            self.close_platform(platform)
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
