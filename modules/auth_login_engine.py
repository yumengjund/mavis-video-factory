"""V1.5.3 Auth Login Engine — 登录自动化层（仅会话复用，不破解）"""
import time
import json
from datetime import datetime


class AuthLoginEngine:
    """平台登录自动化：支持 QR 码登录、Cookie 注入、会话捕获/恢复。

    重要约束：仅做会话复用与恢复，不使用任何绕过/破解手段。
    """

    # 各平台登录 URL / 检测特征
    PLATFORM_CONFIG = {
        "bilibili": {
            "login_url": "https://passport.bilibili.com/login",
            "home_url": "https://www.bilibili.com/",
            "auth_selector": ".header-avatar-wrap, .header-login-entry",
            "auth_invert": False,  # True 表示元素存在 = 未登录
            "cookie_key": "DedeUserID",
        },
        "douyin": {
            "login_url": "https://www.douyin.com/",
            "home_url": "https://www.douyin.com/",
            "auth_selector": None,  # 靠 cookie 判断
            "auth_invert": False,
            "cookie_key": "login_type",
        },
        "xiaohongshu": {
            "login_url": "https://www.xiaohongshu.com/",
            "home_url": "https://www.xiaohongshu.com/explore",
            "auth_selector": ".login-btn, .login-button",
            "auth_invert": True,  # 登录按钮存在 = 未登录
            "cookie_key": "web_session",
        },
        "weibo": {
            "login_url": "https://weibo.com/login.php",
            "home_url": "https://weibo.com/",
            "auth_selector": None,
            "auth_invert": False,
            "cookie_key": "SUB",
        },
    }

    def __init__(self, session_engine, browser_core=None):
        """
        Args:
            session_engine: SessionPersistenceEngine 实例
            browser_core: BrowserCore 实例（可选，仅 inject_cookie 时需要 page）
        """
        self.session = session_engine
        self._browser_core = browser_core

    # ---- 各平台登录方法 -------------------------------------------
    def login_bilibili_qr(self, page):
        """打开 B 站登录页，打印 QR 提示，等待用户扫码完成。"""
        try:
            page.goto(self.PLATFORM_CONFIG["bilibili"]["login_url"],
                      wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            # 等待扫码后页面跳转（最多等 120s）
            page.wait_for_url("https://www.bilibili.com/**", timeout=120000)
            return True
        except Exception:
            return False

    # ---- 通用 Cookie 操作 -----------------------------------------
    def inject_cookie(self, page, platform, cookies):
        """将 cookie 列表注入到浏览器 page 的当前域名下。

        Args:
            page: Playwright Page 实例
            platform: 平台名
            cookies: cookie dict 列表
        """
        if not cookies:
            return False
        try:
            # 先导航到该平台任意页面以设置 domain context
            home = self.PLATFORM_CONFIG.get(platform, {}).get("home_url", "")
            if home:
                page.goto(home, wait_until="domcontentloaded", timeout=15000)
                time.sleep(1)
            page.context.add_cookies(cookies)
            return True
        except Exception:
            return False

    def capture_session(self, page, platform):
        """从当前 page 捕获所有 cookie + 可选 localStorage。

        Returns:
            (cookies_list, metadata_dict)
        """
        try:
            cookies = page.context.cookies()
            # 过滤掉空 value 的 cookie
            cookies = [c for c in cookies if c.get("value")]
            metadata = {
                "platform": platform,
                "last_validated": datetime.now().isoformat(),
                "user_agent": page.evaluate("navigator.userAgent") if page else "",
                "cookie_count": len(cookies),
            }
            return cookies, metadata
        except Exception:
            return [], {}

    def restore_session(self, page, platform):
        """从 session_engine 恢复会话并注入 page。

        Returns:
            bool: 是否成功恢复
        """
        cookies, metadata = self.session.load(platform)
        if not cookies:
            return False
        return self.inject_cookie(page, platform, cookies)

    # ---- 认证检测 ------------------------------------------------
    def is_authenticated(self, page, platform):
        """检查当前 page 是否已登录。

        检测策略：
        - bilibili: 检查页面顶部头像/登录按钮
        - douyin: 检查 cookie 中是否有 login 相关 key
        - xiaohongshu: 检查页面是否显示"登录"按钮
        - weibo: 检查 cookie 中是否有 SUB 字段
        """
        config = self.PLATFORM_CONFIG.get(platform, {})
        if not config:
            return False

        # 策略 1: 通过 Cookie key 判断
        cookie_key = config.get("cookie_key")
        if cookie_key:
            cookies = page.context.cookies() if page else []
            for c in cookies:
                if c.get("name") == cookie_key and c.get("value"):
                    return True

        # 策略 2: 通过页面 DOM 选择器判断
        selector = config.get("auth_selector")
        if selector:
            try:
                el = page.query_selector(selector)
                if config.get("auth_invert", False):
                    # 选择器存在 = 未登录
                    return el is None
                else:
                    return el is not None
            except Exception:
                pass

        return False

    # ---- 自动登录流程 ---------------------------------------------
    def auto_login(self, page, platform):
        """自动恢复会话；失败则提示手动登录。

        Returns:
            dict: {"success": bool, "method": str, "message": str}
        """
        # Step 1: 尝试从 session_engine 恢复
        if self.restore_session(page, platform):
            page.reload(wait_until="domcontentloaded")
            time.sleep(2)
            if self.is_authenticated(page, platform):
                return {"success": True, "method": "session_restore",
                        "message": f"[{platform}] 会话恢复成功"}

        # Step 2: 针对各平台的专用登录流程
        if platform == "bilibili":
            # 尝试 QR 码登录
            result = self.login_bilibili_qr(page)
            if result:
                return {"success": True, "method": "qr_login",
                        "message": f"[{platform}] QR 码登录成功"}
            return {"success": False, "method": "qr_timeout",
                    "message": f"[{platform}] QR 码登录超时或取消，请手动获取 Cookie 后注入"}

        # Step 3: 其他平台 → 提示手动
        return {"success": False, "method": "manual_required",
                "message": f"[{platform}] 无可用自动登录流程。请手动在浏览器登录后，使用 inject_cookie() 注入会话。"}
